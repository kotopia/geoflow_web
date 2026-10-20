"""Retire observation-to-asset relations; source observations and assets are untouched.

Reverse recreates the former schema. The private pre-drop JSON backup is required
for restoring retired relation rows and their audit records (deployment command
--restore). No CASCADE is permitted. Published migration 0044 remains immutable.
"""
from django.db import migrations

FORWARD_SQL = r"""
DROP TABLE IF EXISTS gis.survey_link;
DO $$ BEGIN
  IF to_regclass('gis.feature_change_log') IS NOT NULL THEN
    DELETE FROM gis.feature_change_log WHERE physical_name='survey_link';
    UPDATE gis.feature_change_log
       SET old_values=old_values-'survey_mapping_id'-'survey_id',
           new_values=new_values-'survey_mapping_id'-'survey_id'
     WHERE old_values ? 'survey_mapping_id' OR new_values ? 'survey_mapping_id';
  END IF;
  IF to_regclass('gis.changeset_receipt') IS NOT NULL THEN
    DELETE FROM gis.changeset_receipt r
     WHERE r.response_payload->>'protocol'='survey_link_changeset_v1'
       AND NOT EXISTS (SELECT 1 FROM gis.feature_change_log l
                        WHERE l.project_id=r.project_id AND l.client_id=r.client_id
                          AND l.changeset_id=r.changeset_id);
  END IF;
END $$;
"""
REVERSE_SQL = r"""
        CREATE TABLE IF NOT EXISTS gis.survey_link (
          id uuid PRIMARY KEY,
          survey_id uuid NOT NULL REFERENCES gis.survey(id) ON DELETE RESTRICT,
          layer_id uuid NOT NULL,
          target_id uuid NOT NULL,
          match_method varchar(30) NOT NULL,
          match_distance numeric(12,3),match_confidence numeric(5,4),
          confirmed_by uuid,confirmed_at timestamptz,
          created_at timestamptz NOT NULL DEFAULT now()
        );

        ALTER TABLE gis.survey_link ADD COLUMN IF NOT EXISTS vertex_index integer;
        ALTER TABLE gis.survey_link ADD COLUMN IF NOT EXISTS link_role varchar(20) NOT NULL DEFAULT 'POINT';
        ALTER TABLE gis.survey_link ADD COLUMN IF NOT EXISTS link_status varchar(30) NOT NULL DEFAULT 'LINKED';
        ALTER TABLE gis.survey_link ADD COLUMN IF NOT EXISTS created_by uuid;
        ALTER TABLE gis.survey_link ADD COLUMN IF NOT EXISTS updated_at timestamptz NOT NULL DEFAULT now();
        ALTER TABLE gis.survey_link ADD COLUMN IF NOT EXISTS updated_by uuid;
        DO $$ DECLARE c record; BEGIN
          FOR c IN
            SELECT conname FROM pg_constraint
             WHERE conrelid='gis.survey_link'::regclass AND contype='u'
               AND (pg_get_constraintdef(oid) LIKE 'UNIQUE (survey_id, layer_id, target_id)%'
                    OR pg_get_constraintdef(oid) LIKE 'UNIQUE (survey_id, feature_type_id, target_id)%')
          LOOP
            EXECUTE format('ALTER TABLE gis.survey_link DROP CONSTRAINT %I', c.conname);
          END LOOP;
        END $$;
        DROP INDEX IF EXISTS gis.survey_link_survey_layer_target_uq;
        DO $$ DECLARE c record; BEGIN
          FOR c IN
            SELECT conname FROM pg_constraint
             WHERE conrelid='gis.survey_link'::regclass AND contype='f'
               AND pg_get_constraintdef(oid) LIKE 'FOREIGN KEY (survey_id)%'
          LOOP
            EXECUTE format('ALTER TABLE gis.survey_link DROP CONSTRAINT %I', c.conname);
          END LOOP;
          ALTER TABLE gis.survey_link ADD CONSTRAINT survey_link_survey_id_fk
            FOREIGN KEY(survey_id) REFERENCES gis.survey(id) ON DELETE RESTRICT;
        END $$;
        DO $$ BEGIN
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='gis.survey_link'::regclass AND conname='survey_link_role_ck') THEN
            ALTER TABLE gis.survey_link ADD CONSTRAINT survey_link_role_ck
              CHECK (link_role IN ('POINT','VERTEX'));
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='gis.survey_link'::regclass AND conname='survey_link_status_ck') THEN
            ALTER TABLE gis.survey_link ADD CONSTRAINT survey_link_status_ck
              CHECK (link_status IN ('LINKED','MANUALLY_MODIFIED','UNLINKED'));
          END IF;
          IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conrelid='gis.survey_link'::regclass AND conname='survey_link_vertex_ck') THEN
            ALTER TABLE gis.survey_link ADD CONSTRAINT survey_link_vertex_ck CHECK (
              (link_role='POINT' AND vertex_index IS NULL) OR
              (link_role='VERTEX' AND vertex_index IS NOT NULL AND vertex_index >= 0)
            );
          END IF;
        END $$;
        CREATE UNIQUE INDEX IF NOT EXISTS survey_link_active_target_uq
          ON gis.survey_link(layer_id, target_id, COALESCE(vertex_index,-1))
          WHERE link_status <> 'UNLINKED';
        CREATE INDEX IF NOT EXISTS survey_link_survey_status_idx
          ON gis.survey_link(survey_id, link_status);
        CREATE INDEX IF NOT EXISTS survey_link_target_vertex_idx
          ON gis.survey_link(layer_id, target_id, vertex_index);
        CREATE INDEX IF NOT EXISTS survey_link_status_idx ON gis.survey_link(link_status);
"""

class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0046_gis_survey_final_fields")]
    operations = [migrations.RunSQL(FORWARD_SQL, reverse_sql=REVERSE_SQL)]
