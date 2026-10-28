"""Tenant scope selection: central UUIDs are validated at the service boundary."""
from django.db import migrations

SQL = '''CREATE TABLE gis.project_reference_group (
    project_id uuid NOT NULL REFERENCES prj.projects(id) ON DELETE CASCADE,
    catalog_l2_id uuid NOT NULL,
    group_id uuid NOT NULL,
    PRIMARY KEY(project_id,catalog_l2_id,group_id)
);
CREATE INDEX project_reference_group_group_idx ON gis.project_reference_group(group_id);'''


class Migration(migrations.Migration):
    dependencies = [('webgisapp', '0047_remove_survey_targets')]
    operations = [migrations.RunSQL(SQL, 'DROP TABLE gis.project_reference_group')]
