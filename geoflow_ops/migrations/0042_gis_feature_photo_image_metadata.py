"""Add file metadata storage independently from photo business extra_data."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [("webgisapp", "0041_gis_feature_photo_edited_representation")]

    operations = [migrations.RunSQL(
        sql="""
        ALTER TABLE gis.feature_photo
          ADD COLUMN IF NOT EXISTS image_metadata jsonb NOT NULL DEFAULT '{}'::jsonb;
        ALTER TABLE gis.feature_photo DROP CONSTRAINT IF EXISTS feature_photo_image_metadata_check;
        ALTER TABLE gis.feature_photo ADD CONSTRAINT feature_photo_image_metadata_check
          CHECK(jsonb_typeof(image_metadata)='object');
        """,
        reverse_sql=migrations.RunSQL.noop,
    )]
