"""Central code applicability; empty relations preserve all legacy common values."""
from django.db import migrations

SQL = '''CREATE TABLE IF NOT EXISTS gis.definition_code_group (
    code_id uuid NOT NULL REFERENCES gis.definition_code(id) ON DELETE CASCADE,
    group_id uuid NOT NULL REFERENCES gis.definition_group(id) ON DELETE RESTRICT,
    sort_order integer NOT NULL DEFAULT 0,
    PRIMARY KEY(code_id,group_id)
);
CREATE INDEX IF NOT EXISTS definition_code_group_group_idx ON gis.definition_code_group(group_id);'''


def forward(apps, schema_editor):
    with schema_editor.connection.cursor() as cursor:
        cursor.execute("SELECT to_regclass('gis.definition_code')")
        if cursor.fetchone()[0]:
            cursor.execute(SQL)
        # Fresh central installs without GIS use the GIS foundation bootstrap,
        # whose canonical SQL also creates this relation after definition_code.


def reverse(apps, schema_editor):
    schema_editor.execute('DROP TABLE IF EXISTS gis.definition_code_group')


class Migration(migrations.Migration):
    dependencies = [('control', '0008_saved_filters')]
    operations = [migrations.RunPython(forward, reverse)]
