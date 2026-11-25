"""Central spatial-reference catalogue; independent of enum definition_code."""

from typing import ClassVar

from django.db import migrations

SQL = """
CREATE SCHEMA IF NOT EXISTS gis;
CREATE TABLE gis.reference_source (
    id uuid PRIMARY KEY,
    name varchar(160) NOT NULL,
    kind text NOT NULL CHECK (kind IN ('manual', 'api', 'file_url', 'page')),
    url text NOT NULL DEFAULT '',
    secret_ref text NOT NULL DEFAULT '',
    enabled boolean NOT NULL DEFAULT true,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE TABLE gis.reference_dataset (
    id uuid PRIMARY KEY,
    code varchar(64) NOT NULL UNIQUE,
    name varchar(160) NOT NULL,
    kind text NOT NULL CHECK (kind IN
        ('map_sheet', 'legal_boundary', 'admin_boundary', 'cadastral',
         'cadastral_control', 'integrated_control', 'local_control', 'other')),
    region varchar(160) NOT NULL DEFAULT '',
    publisher varchar(160) NOT NULL DEFAULT '',
    description text NOT NULL DEFAULT '',
    usage_terms text NOT NULL DEFAULT '',
    source_id uuid REFERENCES gis.reference_source(id) ON DELETE RESTRICT,
    enabled boolean NOT NULL DEFAULT true,
    revision integer NOT NULL DEFAULT 1 CHECK (revision > 0),
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX reference_dataset_source_idx ON gis.reference_dataset(source_id);
CREATE TABLE gis.reference_version (
    id uuid PRIMARY KEY,
    dataset_id uuid NOT NULL REFERENCES gis.reference_dataset(id) ON DELETE RESTRICT,
    label varchar(120) NOT NULL,
    published_on date,
    declared_crs varchar(40) NOT NULL DEFAULT '',
    filename varchar(180) NOT NULL,
    size_bytes bigint NOT NULL CHECK (size_bytes > 0),
    sha256 char(64) NOT NULL,
    object_key text NOT NULL UNIQUE,
    status text NOT NULL CHECK (status IN ('pending', 'stored', 'failed')),
    error_code text NOT NULL DEFAULT '',
    created_at timestamptz NOT NULL DEFAULT now(),
    updated_at timestamptz NOT NULL DEFAULT now(),
    UNIQUE(dataset_id, label)
);
CREATE INDEX reference_version_dataset_idx ON gis.reference_version(dataset_id, created_at DESC);
CREATE TABLE gis.reference_event (
    id uuid PRIMARY KEY,
    actor_id uuid NOT NULL,
    dataset_id uuid REFERENCES gis.reference_dataset(id) ON DELETE RESTRICT,
    source_id uuid REFERENCES gis.reference_source(id) ON DELETE RESTRICT,
    version_id uuid REFERENCES gis.reference_version(id) ON DELETE RESTRICT,
    action text NOT NULL CHECK (action IN
        ('dataset_created', 'dataset_updated', 'source_created', 'source_updated',
         'upload_started', 'upload_stored', 'upload_failed')),
    created_at timestamptz NOT NULL DEFAULT now()
);
CREATE INDEX reference_event_recent_idx ON gis.reference_event(created_at DESC, id);
"""


class Migration(migrations.Migration):
    dependencies: ClassVar = [("control", "0010_tenant_employee_registrations")]
    # Original files and audit rows must survive a code rollback. No destructive reverse.
    operations: ClassVar = [migrations.RunSQL(SQL, reverse_sql=migrations.RunSQL.noop)]
