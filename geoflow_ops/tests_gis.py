from django.test import SimpleTestCase

from geoflow_ops.gis.registry import FEATURE_TYPES, domain_counts, feature_rows


class GisFeatureRegistryTests(SimpleTestCase):
    def test_initial_registry_matches_approved_scope(self):
        names = {item.standard_name for item in FEATURE_TYPES}

        self.assertEqual(len(FEATURE_TYPES), 19)
        self.assertIn("DORO", names)
        self.assertIn("SURVEY", names)
        self.assertIn("WTL_PIPE_LM", names)
        self.assertIn("WTL_VALV_PS", names)
        self.assertIn("SWL_PIPE_LM", names)
        self.assertNotIn("POLYGON", names)
        self.assertNotIn("WTL_ERROR", names)
        self.assertNotIn("SWL_ERROR", names)
        self.assertNotIn("H_SURVEY", names)

    def test_physical_names_are_lowercase_and_gis_scoped(self):
        for row in feature_rows():
            self.assertEqual(row["physical_name"], row["physical_name"].lower())
            self.assertEqual(row["db_name"], f"gis.{row['physical_name']}")

    def test_domain_counts(self):
        counts = {item["code"]: item["count"] for item in domain_counts()}
        self.assertEqual(counts, {"COMMON": 2, "WTL": 9, "SWL": 8})
