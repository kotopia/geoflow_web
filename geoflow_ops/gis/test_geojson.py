from django.test import SimpleTestCase

from .views import _parse_bbox, _parse_limit, _registry_feature


class GisGeoJsonHelperTests(SimpleTestCase):
    def test_registry_accepts_standard_and_physical_names(self):
        standard = _registry_feature("WTL_PIPE_LM")
        physical = _registry_feature("wtl_pipe_lm")

        self.assertIsNotNone(standard)
        self.assertIsNotNone(physical)
        self.assertEqual(standard.standard_name, "WTL_PIPE_LM")
        self.assertEqual(physical.physical_name, "wtl_pipe_lm")

    def test_registry_rejects_unreviewed_table_name(self):
        self.assertIsNone(_registry_feature("pg_catalog.pg_tables"))
        self.assertIsNone(_registry_feature("wtl_pipe_lm;drop table x"))

    def test_bbox_accepts_valid_epsg4326_extent(self):
        self.assertEqual(
            _parse_bbox("127.0,36.7,127.2,36.9"),
            (127.0, 36.7, 127.2, 36.9),
        )

    def test_bbox_rejects_invalid_or_reversed_extent(self):
        with self.assertRaises(ValueError):
            _parse_bbox("127,36,126,37")
        with self.assertRaises(ValueError):
            _parse_bbox("127,36,127.1")
        with self.assertRaises(ValueError):
            _parse_bbox("200,36,201,37")

    def test_limit_defaults_and_caps(self):
        self.assertEqual(_parse_limit(None), 2000)
        self.assertEqual(_parse_limit("100"), 100)
        self.assertEqual(_parse_limit("99999"), 5000)
        with self.assertRaises(ValueError):
            _parse_limit("0")
