"""Join the central-bid and tenant-GIS-photo migration branches."""
from django.db import migrations


class Migration(migrations.Migration):
    dependencies = [
        ("webgisapp", "0038_bid_central_preferences"),
        ("webgisapp", "0039_gis_feature_photo"),
    ]
    operations = []
