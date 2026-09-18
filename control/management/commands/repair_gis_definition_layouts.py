"""Normalize legacy non-object definition-field layout values."""
import json
import os
from pathlib import Path

from django.core.management.base import BaseCommand, CommandError
from django.db import connections, transaction


def normalize_layout(value):
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            decoded = json.loads(value)
        except (TypeError, ValueError):
            decoded = None
        if isinstance(decoded, dict):
            return decoded
    return {}


def recoverable_string_object(value):
    if not isinstance(value, str):
        return False
    try:
        return isinstance(json.loads(value), dict)
    except (TypeError, ValueError):
        return False


class Command(BaseCommand):
    help = "Back up and normalize legacy definition_field.layout values to JSON objects"

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true")
        parser.add_argument("--backup-file", required=True)

    def handle(self, *args, **options):
        if not options["apply"]:
            raise CommandError("Explicit --apply required")
        backup = Path(options["backup_file"]).resolve()
        backup.parent.mkdir(mode=0o700, parents=True, exist_ok=True)

        with transaction.atomic(using="default"), connections["default"].cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='5s'")
            cursor.execute("SET LOCAL statement_timeout='60s'")
            cursor.execute("""SELECT id::text, layout, jsonb_typeof(layout)
                FROM gis.definition_field
                WHERE jsonb_typeof(layout) IS DISTINCT FROM 'object'
                ORDER BY id FOR UPDATE""")
            invalid = cursor.fetchall()
            audit = [
                {"id": field_id, "layout": layout, "json_type": json_type}
                for field_id, layout, json_type in invalid
            ]
            if not backup.exists():
                descriptor = os.open(backup, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(descriptor, "w") as output:
                    json.dump(audit, output, ensure_ascii=False, default=str, indent=2)

            repaired_objects = 0
            reset_values = 0
            for field_id, layout, _json_type in invalid:
                normalized = normalize_layout(layout)
                recovered = recoverable_string_object(layout)
                repaired_objects += int(recovered)
                reset_values += int(not recovered)
                cursor.execute(
                    "UPDATE gis.definition_field SET layout=%s::jsonb WHERE id=%s",
                    [json.dumps(normalized, ensure_ascii=False), field_id],
                )

            cursor.execute("""SELECT count(*) FROM gis.definition_field
                WHERE jsonb_typeof(layout) IS DISTINCT FROM 'object'""")
            remaining = cursor.fetchone()[0]
            if remaining:
                raise CommandError(f"gis_definition_layout_non_object_remaining={remaining}")

        self.stdout.write(f"gis_definition_layout_non_object_found={len(invalid)}")
        self.stdout.write(f"gis_definition_layout_string_objects_restored={repaired_objects}")
        self.stdout.write(f"gis_definition_layout_values_reset={reset_values}")
        self.stdout.write("gis_definition_layout_non_object_remaining=0")
