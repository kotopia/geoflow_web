"""Read-only row-count guard for code-only central GIS UI releases."""
from __future__ import annotations

import json
import hashlib
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections


TABLES = (
    "definition_group",
    "definition_layer",
    "definition_layer_catalog",
    "definition_field",
    "definition_field_layer",
    "definition_code",
    "definition_rule",
)


def inventory(cursor):
    row_counts = {}
    fingerprints = {}
    for table in TABLES:
        cursor.execute(f"SELECT count(*) FROM gis.{table}")
        row_counts[table] = int(cursor.fetchone()[0])
        cursor.execute(f"SELECT to_jsonb(item) FROM gis.{table} item ORDER BY to_jsonb(item)::text")
        payload = json.dumps(cursor.fetchall(), sort_keys=True, default=str, separators=(",", ":"))
        fingerprints[table] = hashlib.sha256(payload.encode()).hexdigest()
    return {"counts": row_counts, "fingerprints": fingerprints}


class Command(BaseCommand):
    help = "Record or compare row counts for central GIS definition tables"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--write", type=Path)
        group.add_argument("--compare", type=Path)

    def handle(self, *args, **options):
        with connections["default"].cursor() as cursor:
            current = inventory(cursor)
        target = options["write"] or options["compare"]
        if options["write"]:
            target.write_text(json.dumps(current, sort_keys=True) + "\n")
            self.stdout.write("gis_definition_row_counts_before=" + json.dumps(current["counts"], sort_keys=True))
            return
        try:
            expected = json.loads(target.read_text())
        except (OSError, ValueError) as exc:
            raise CommandError("gis_definition_row_count_baseline_invalid") from exc
        if current != expected:
            raise CommandError(
                "gis_definition_inventory_changed before="
                + json.dumps(expected, sort_keys=True)
                + " after="
                + json.dumps(current, sort_keys=True)
            )
        self.stdout.write("gis_definition_row_counts_after=" + json.dumps(current["counts"], sort_keys=True))
        self.stdout.write("gis_definition_row_counts_unchanged=yes")
        self.stdout.write("gis_definition_relationship_fingerprints_unchanged=yes")
