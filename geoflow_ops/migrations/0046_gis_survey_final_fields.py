"""Constrain existing final Survey fields; separate source method and target CRS.

The operational command inventories and backs up rows before applying this SQL.
No provenance values or existing final values are changed by the schema migration.
"""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [('webgisapp', '0045_gis_survey_soft_delete')]
    operations = [migrations.RunSQL(
        sql=r"""
        ALTER TABLE gis.survey ADD COLUMN IF NOT EXISTS survey_no varchar(30);
        ALTER TABLE gis.survey_source ADD COLUMN IF NOT EXISTS survey_type varchar(20);
        ALTER TABLE gis.survey_source ADD COLUMN IF NOT EXISTS target_crs text;
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='gis.survey'::regclass AND conname='survey_project_no_uq') THEN
            ALTER TABLE gis.survey ADD CONSTRAINT survey_project_no_uq UNIQUE(project_id,survey_no);
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='gis.survey'::regclass AND conname='survey_type_ck') THEN
            ALTER TABLE gis.survey ADD CONSTRAINT survey_type_ck CHECK(type IN ('GNSS','TOTAL_STATION'));
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='gis.survey_source'::regclass AND conname='survey_source_method_ck') THEN
            ALTER TABLE gis.survey_source ADD CONSTRAINT survey_source_method_ck CHECK(survey_type IN ('GNSS','TOTAL_STATION'));
          END IF;
        END $$;
        """,
        # Roll back application code without deleting final values or lineage.
        reverse_sql=migrations.RunSQL.noop,
    )]
