-- GeoFlow GIS Changeset/Revision support v1
-- DEVELOPMENT / REPOSITORY FOUNDATION ONLY.
-- Do not run against a production tenant DB without separate explicit approval.
-- This file is intentionally migration-free and guarded for dev/test rehearsal.

BEGIN;

DO $$
BEGIN
    IF current_database() NOT ILIKE '%dev%' AND current_database() NOT ILIKE '%test%' THEN
        RAISE EXCEPTION 'Safety stop: GIS sync revision DDL may run only in a dev/test database. Current DB: %', current_database();
    END IF;
    IF to_regclass('prj.projects') IS NULL THEN
        RAISE EXCEPTION 'GeoFlow tenant base schema is missing: prj.projects not found.';
    END IF;
    IF to_regclass('gis.meta_feature_type') IS NULL THEN
        RAISE EXCEPTION 'GeoFlow GIS foundation is missing: gis.meta_feature_type not found.';
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS gis.project_sync_state (
    project_id uuid PRIMARY KEY REFERENCES prj.projects(id),
    current_revision bigint NOT NULL DEFAULT 0 CHECK (current_revision >= 0),
    snapshot_revision bigint NOT NULL DEFAULT 0 CHECK (snapshot_revision >= 0),
    updated_at timestamptz NOT NULL DEFAULT now(),
    CHECK (snapshot_revision <= current_revision)
);

COMMENT ON TABLE gis.project_sync_state IS
'Per-project authoritative GIS revision state. current_revision advances once per committed object change; snapshot_revision identifies the latest reusable server snapshot baseline.';

CREATE TABLE IF NOT EXISTS gis.changeset_receipt (
    project_id uuid NOT NULL REFERENCES prj.projects(id),
    client_id uuid NOT NULL,
    changeset_id uuid NOT NULL,
    actor_ref text,
    base_revision bigint,
    first_revision bigint,
    last_revision bigint,
    change_count integer NOT NULL DEFAULT 0 CHECK (change_count >= 0),
    response_payload jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, client_id, changeset_id),
    CHECK (base_revision IS NULL OR base_revision >= 0),
    CHECK (first_revision IS NULL OR first_revision >= 1),
    CHECK (last_revision IS NULL OR last_revision >= first_revision)
);

CREATE INDEX IF NOT EXISTS changeset_receipt_project_created_idx
    ON gis.changeset_receipt(project_id, created_at DESC);

COMMENT ON TABLE gis.changeset_receipt IS
'Idempotency receipt for client Changeset retries. Repeating the same project/client/changeset key must return the recorded response rather than reapply writes.';

CREATE TABLE IF NOT EXISTS gis.feature_change_log (
    project_id uuid NOT NULL REFERENCES prj.projects(id),
    revision bigint NOT NULL CHECK (revision >= 1),
    changeset_id uuid NOT NULL,
    client_id uuid NOT NULL,
    standard_name text NOT NULL,
    physical_name text NOT NULL,
    object_id uuid NOT NULL,
    action varchar(10) NOT NULL CHECK (action IN ('create', 'update', 'delete')),
    changed_fields jsonb NOT NULL DEFAULT '[]'::jsonb,
    old_values jsonb NOT NULL DEFAULT '{}'::jsonb,
    new_values jsonb NOT NULL DEFAULT '{}'::jsonb,
    geom_before geometry(Geometry, 4326),
    geom_after geometry(Geometry, 4326),
    actor_ref text,
    created_at timestamptz NOT NULL DEFAULT now(),
    PRIMARY KEY (project_id, revision),
    FOREIGN KEY (project_id, client_id, changeset_id)
        REFERENCES gis.changeset_receipt(project_id, client_id, changeset_id)
        DEFERRABLE INITIALLY DEFERRED
);

CREATE INDEX IF NOT EXISTS feature_change_log_project_object_idx
    ON gis.feature_change_log(project_id, physical_name, object_id, revision DESC);
CREATE INDEX IF NOT EXISTS feature_change_log_project_changeset_idx
    ON gis.feature_change_log(project_id, client_id, changeset_id);
CREATE INDEX IF NOT EXISTS feature_change_log_project_created_idx
    ON gis.feature_change_log(project_id, created_at DESC);

COMMENT ON TABLE gis.feature_change_log IS
'Ordered object-level project Delta and audit history. Attribute payloads contain only the changed patch except create, which records the complete server-approved editable state.';

-- Seed state rows for existing projects without advancing revisions.
INSERT INTO gis.project_sync_state(project_id, current_revision, snapshot_revision)
SELECT p.id, 0, 0
FROM prj.projects p
ON CONFLICT (project_id) DO NOTHING;

COMMIT;
