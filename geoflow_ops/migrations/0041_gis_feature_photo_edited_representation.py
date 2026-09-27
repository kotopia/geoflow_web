"""Tenant GIS photo edited representation while preserving the original object."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0040_merge_bid_photo_branches")]

    operations = [migrations.RunSQL(
        sql="""
        ALTER TABLE gis.feature_photo
          ADD COLUMN IF NOT EXISTS edited_object_key text,
          ADD COLUMN IF NOT EXISTS edited_mime_type text,
          ADD COLUMN IF NOT EXISTS edited_size_bytes bigint,
          ADD COLUMN IF NOT EXISTS edited_at timestamptz,
          ADD COLUMN IF NOT EXISTS edited_by uuid,
          ADD COLUMN IF NOT EXISTS edit_data jsonb NOT NULL DEFAULT '{}'::jsonb;
        CREATE UNIQUE INDEX IF NOT EXISTS feature_photo_edited_object_key_uq
          ON gis.feature_photo(edited_object_key) WHERE edited_object_key IS NOT NULL;
        ALTER TABLE gis.feature_photo DROP CONSTRAINT IF EXISTS feature_photo_edited_size_check;
        ALTER TABLE gis.feature_photo ADD CONSTRAINT feature_photo_edited_size_check
          CHECK(edited_size_bytes IS NULL OR edited_size_bytes > 0);
        ALTER TABLE gis.feature_photo DROP CONSTRAINT IF EXISTS feature_photo_edit_data_check;
        ALTER TABLE gis.feature_photo ADD CONSTRAINT feature_photo_edit_data_check
          CHECK(jsonb_typeof(edit_data)='object');
        """,
        reverse_sql=migrations.RunSQL.noop,
    )]
