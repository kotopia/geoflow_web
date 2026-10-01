"""Versioned survey sources and vertex-aware survey lineage.

Repository migration only. Production application requires separate approval.
"""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0043_gis_feature_photo_catalog_v2")]

    operations = [migrations.RunSQL(
        sql=r"""
        CREATE SCHEMA IF NOT EXISTS gis;

        -- Keep a freshly provisioned tenant migratable even when the separate
        -- GIS foundation bootstrap has not run yet. Existing tables are never rebuilt.
        CREATE TABLE IF NOT EXISTS gis.survey (
          id uuid PRIMARY KEY,
          project_id uuid NOT NULL REFERENCES prj.projects(id) ON DELETE RESTRICT,
          worker_id uuid,name varchar(30),code varchar(30),survey_code varchar(30),
          survey_date date,surveyed_at timestamptz,
          raw_x numeric(20,3),raw_y numeric(20,3),raw_z numeric(10,3),
          x numeric(20,3),y numeric(20,3),z numeric(10,3),
          latitude double precision,longitude double precision,
          solution_info varchar(200),pdop double precision,antenna_height numeric(8,3),
          filter varchar(20),type varchar(20),raw_data jsonb NOT NULL DEFAULT '{}'::jsonb,
          raw_geom geometry(Point,4326),geom geometry(Point,4326),description text,
          created_at timestamptz NOT NULL DEFAULT now(),updated_at timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX IF NOT EXISTS survey_project_idx ON gis.survey(project_id);
        CREATE INDEX IF NOT EXISTS survey_geom_gix ON gis.survey USING gist(geom);

        CREATE TABLE IF NOT EXISTS gis.survey_source (
          id uuid PRIMARY KEY,
          project_id uuid NOT NULL REFERENCES prj.projects(id) ON DELETE RESTRICT,
          source_group_id uuid NOT NULL,
          supersedes_id uuid REFERENCES gis.survey_source(id) ON DELETE RESTRICT,
          source_type varchar(20) NOT NULL,
          original_file_name text NOT NULL,
          original_file_key text,
          imported_at timestamptz NOT NULL DEFAULT now(),
          imported_by uuid,
          source_crs text,
          geoid_model text,
          calibration_info jsonb NOT NULL DEFAULT '{}'::jsonb,
          version integer NOT NULL CHECK (version > 0),
          is_active boolean NOT NULL DEFAULT true,
          note text NOT NULL DEFAULT '',
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          CHECK (source_type IN ('GNSS','GPS','TOTAL','CSV','XLSX','OTHER')),
          CHECK (jsonb_typeof(calibration_info) = 'object'),
          UNIQUE(project_id, source_group_id, version)
        );
        CREATE INDEX IF NOT EXISTS survey_source_project_idx
          ON gis.survey_source(project_id, imported_at DESC);
        CREATE UNIQUE INDEX IF NOT EXISTS survey_source_active_group_uq
          ON gis.survey_source(project_id, source_group_id) WHERE is_active;

        ALTER TABLE gis.survey ADD COLUMN IF NOT EXISTS source_id uuid;
        ALTER TABLE gis.survey ADD COLUMN IF NOT EXISTS source_row_id text;
        ALTER TABLE gis.survey ADD COLUMN IF NOT EXISTS raw_crs text;
        ALTER TABLE gis.survey ADD COLUMN IF NOT EXISTS raw_code text;
        ALTER TABLE gis.survey ADD COLUMN IF NOT EXISTS raw_geoid_model text;
        DO $$ BEGIN
          IF NOT EXISTS (
            SELECT 1 FROM pg_constraint
             WHERE conrelid='gis.survey'::regclass AND conname='survey_source_id_fk'
          ) THEN
            ALTER TABLE gis.survey ADD CONSTRAINT survey_source_id_fk
              FOREIGN KEY(source_id) REFERENCES gis.survey_source(id) ON DELETE RESTRICT;
          END IF;
        END $$;
        CREATE INDEX IF NOT EXISTS survey_source_idx ON gis.survey(source_id);
        CREATE INDEX IF NOT EXISTS survey_source_row_idx ON gis.survey(source_row_id);
        CREATE UNIQUE INDEX IF NOT EXISTS survey_source_row_uq
          ON gis.survey(source_id, source_row_id)
          WHERE source_id IS NOT NULL AND source_row_id IS NOT NULL;

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
        """,
        reverse_sql=migrations.RunSQL.noop,
    )]
