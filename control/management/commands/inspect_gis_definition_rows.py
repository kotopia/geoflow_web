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


SURVEY_FINAL_NAMES = frozenset({'survey_no','type','x','y','z'})


def inventory(cursor, *, survey_final_readonly=False, expected_transition=False):
    row_counts = {}
    fingerprints = {}
    for table in TABLES:
        cursor.execute(f"SELECT count(*) FROM gis.{table}")
        row_counts[table] = int(cursor.fetchone()[0])
        if table == 'definition_field' and survey_final_readonly:
            cursor.execute("""SELECT to_jsonb(item),
                       layer.physical_name='survey' AND item.physical_name=ANY(%s)
                  FROM gis.definition_field item
                  LEFT JOIN gis.definition_layer layer ON layer.id=item.source_layer_id
                 ORDER BY item.id""", [sorted(SURVEY_FINAL_NAMES)])
            values = []
            target_names = []
            for value, is_target in cursor.fetchall():
                value = json.loads(value) if isinstance(value,str) else dict(value)
                if is_target:
                    target_names.append(value['physical_name'])
                    # This exact transition changes readonly and its audit time.
                    # On compare, actual readonly must be true; other fields,
                    # rows, relationships, labels and storage remain fingerprinted.
                    if expected_transition:
                        value['readonly'] = True
                    value.pop('updated_at', None)
                values.append((value,))
            if len(target_names) != 5 or set(target_names) != SURVEY_FINAL_NAMES:
                raise CommandError('gis_survey_final_definition_targets_invalid')
        else:
            cursor.execute(f"SELECT to_jsonb(item) FROM gis.{table} item ORDER BY to_jsonb(item)::text")
            values = cursor.fetchall()
        payload = json.dumps(values, sort_keys=True, default=str, separators=(",", ":"))
        fingerprints[table] = hashlib.sha256(payload.encode()).hexdigest()
    result = {"counts": row_counts, "fingerprints": fingerprints}
    if survey_final_readonly:
        result['authorized_transition'] = 'survey_final_readonly_v1'
    return result


class Command(BaseCommand):
    help = "Record or compare row counts for central GIS definition tables"

    def add_arguments(self, parser):
        group = parser.add_mutually_exclusive_group(required=True)
        group.add_argument("--write", type=Path)
        group.add_argument("--compare", type=Path)
        parser.add_argument("--survey-final-readonly", action="store_true")

    def handle(self, *args, **options):
        with connections["default"].cursor() as cursor:
            current = inventory(cursor,
                survey_final_readonly=options['survey_final_readonly'],
                expected_transition=bool(options['write']))
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
        if options['survey_final_readonly']:
            self.stdout.write('gis_definition_survey_final_readonly_transition=verified')
        self.stdout.write("gis_definition_row_counts_after=" + json.dumps(current["counts"], sort_keys=True))
        self.stdout.write("gis_definition_row_counts_unchanged=yes")
        self.stdout.write("gis_definition_relationship_fingerprints_unchanged=yes")
