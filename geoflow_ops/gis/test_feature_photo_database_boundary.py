from django.test import SimpleTestCase

from geoflow_ops.gis.feature_photo_views import (
    _image_metadata,
    _postgres_json,
    _postgres_text,
)


class FeaturePhotoDatabaseBoundaryTests(SimpleTestCase):
    def test_postgres_text_removes_nul_only(self):
        self.assertEqual(_postgres_text("camera\x00 model"), "camera model")

    def test_postgres_json_normalizes_nested_metadata(self):
        value = {
            "exif": {"Model": "GNSS\x00Camera"},
            "gps": {"values": [1, "north\x00"]},
        }
        self.assertEqual(
            _postgres_json(value),
            {
                "exif": {"Model": "GNSSCamera"},
                "gps": {"values": [1, "north"]},
            },
        )

    def test_image_metadata_returns_postgres_safe_json(self):
        value = _image_metadata({"exif": {"UserComment": "field\x00photo"}})
        self.assertEqual(value["exif"]["UserComment"], "fieldphoto")

