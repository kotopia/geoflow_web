"""Tenant GIS photo rows; separate from ops.attachments.

Repository migration only. Production application requires separate approval.
"""
from django.db import migrations


class Migration(migrations.Migration):
    # The bid 0037/0038 branch is installed only in central bid stores.  GIS
    # photos belong in every tenant, so this branch starts at the last common
    # tenant migration.
    dependencies = [("webgisapp", "0036_bid_interest_foundation")]

    operations = [migrations.RunSQL(
        sql="""
        CREATE SCHEMA IF NOT EXISTS gis;
        CREATE TABLE IF NOT EXISTS gis.feature_photo (
          id uuid PRIMARY KEY,
          project_id uuid NOT NULL,
          layer_id uuid NOT NULL,
          feature_id uuid NOT NULL,
          slot_id uuid,
          object_key text NOT NULL UNIQUE,
          original_name text NOT NULL,
          mime_type text NOT NULL,
          size_bytes bigint NOT NULL CHECK(size_bytes > 0),
          sha256 text,
          captured_at timestamptz,
          captured_by uuid,
          sort_order integer NOT NULL DEFAULT 0,
          note text NOT NULL DEFAULT '',
          extra_data jsonb NOT NULL DEFAULT '{}'::jsonb CHECK(jsonb_typeof(extra_data)='object'),
          created_at timestamptz NOT NULL DEFAULT now(),
          updated_at timestamptz NOT NULL DEFAULT now(),
          deleted_at timestamptz,
          deleted_by text
        );
        CREATE INDEX IF NOT EXISTS feature_photo_feature_idx
          ON gis.feature_photo(project_id,layer_id,feature_id,sort_order)
          WHERE deleted_at IS NULL;
        CREATE INDEX IF NOT EXISTS feature_photo_slot_idx
          ON gis.feature_photo(project_id,slot_id) WHERE deleted_at IS NULL;
        """,
        reverse_sql=migrations.RunSQL.noop,
    )]
