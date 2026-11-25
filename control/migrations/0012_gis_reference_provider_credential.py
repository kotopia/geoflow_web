"""One version-pinned server credential per reference provider; no key material."""

from typing import ClassVar

from django.db import migrations

SQL = """
CREATE TABLE gis.reference_provider_credential (
    provider varchar(40) PRIMARY KEY,
    secret_version varchar(64) NOT NULL,
    domain varchar(300) NOT NULL,
    revision integer NOT NULL CHECK (revision > 0),
    actor_id uuid NOT NULL,
    updated_at timestamptz NOT NULL DEFAULT now()
);
ALTER TABLE gis.reference_event DROP CONSTRAINT reference_event_action_check;
ALTER TABLE gis.reference_event ADD CONSTRAINT reference_event_action_check CHECK (action IN
    ('dataset_created','dataset_updated','source_created','source_updated',
     'upload_started','upload_stored','upload_failed','credential_updated'));
"""


class Migration(migrations.Migration):
    dependencies: ClassVar = [("control", "0011_gis_reference_datasets")]
    operations: ClassVar = [migrations.RunSQL(SQL, reverse_sql=migrations.RunSQL.noop)]
