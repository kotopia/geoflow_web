"""Add non-destructive Survey source/point deletion metadata."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0044_gis_survey_lineage")]

    operations = [migrations.RunSQL(
        sql=r"""
        ALTER TABLE gis.survey_source ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
        ALTER TABLE gis.survey_source ADD COLUMN IF NOT EXISTS deleted_by uuid;
        ALTER TABLE gis.survey_source ADD COLUMN IF NOT EXISTS delete_reason text;

        ALTER TABLE gis.survey ADD COLUMN IF NOT EXISTS deleted_at timestamptz;
        ALTER TABLE gis.survey ADD COLUMN IF NOT EXISTS deleted_by uuid;
        ALTER TABLE gis.survey ADD COLUMN IF NOT EXISTS delete_reason text;

        CREATE INDEX IF NOT EXISTS survey_source_visible_project_idx
          ON gis.survey_source(project_id, imported_at DESC) WHERE deleted_at IS NULL;
        CREATE INDEX IF NOT EXISTS survey_visible_project_idx
          ON gis.survey(project_id, source_id, source_row_id) WHERE deleted_at IS NULL;
        """,
        reverse_sql=migrations.RunSQL.noop,
    )]
