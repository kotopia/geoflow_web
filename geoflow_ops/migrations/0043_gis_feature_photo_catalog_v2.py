"""Add central catalogue identities and a user-facing title to tenant photos."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0042_gis_feature_photo_image_metadata")]

    operations = [migrations.RunSQL(
        sql="""
        ALTER TABLE gis.feature_photo ADD COLUMN IF NOT EXISTS template_id uuid;
        ALTER TABLE gis.feature_photo ADD COLUMN IF NOT EXISTS variant_id uuid;
        ALTER TABLE gis.feature_photo ADD COLUMN IF NOT EXISTS title text NOT NULL DEFAULT '';
        CREATE INDEX IF NOT EXISTS feature_photo_catalog_idx
          ON gis.feature_photo(project_id,layer_id,template_id,variant_id,slot_id)
          WHERE deleted_at IS NULL;
        -- Legacy pre-service rows can remain readable until an explicitly approved
        -- DB/S3 cleanup. New writes enforce all-three-or-none in the server API.
        """,
        reverse_sql=migrations.RunSQL.noop,
    )]
