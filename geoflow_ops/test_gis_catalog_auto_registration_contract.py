from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class GISCatalogAutoRegistrationContractTests(unittest.TestCase):
    def setUp(self):
        self.layer_plan = (ROOT / "geoflow_ops/gis/layer_plan.py").read_text()
        self.sync_script = (
            ROOT / "scripts/ops/sync_gis_catalog_capability_bindings.py"
        ).read_text()

    def test_live_layer_plan_prefers_production_profile_with_dev_fallback(self):
        self.assertIn(
            'DEFAULT_PROFILE_CODES = ("GEOFLOW_BASE_V1", "GEOFLOW_DEV_BASE")',
            self.layer_plan,
        )
        self.assertIn("p.code=ANY(%s::text[])", self.layer_plan)
        self.assertIn("array_position(%s::text[], p.code)", self.layer_plan)

    def test_registration_is_derived_live_from_business_scope(self):
        for relation in (
            "prj.scope_item",
            "gis.scope_binding",
            "gis.capability_feature",
            "gis.profile_feature",
        ):
            self.assertIn(relation, self.layer_plan)
        lowered = self.layer_plan.lower()
        for forbidden in ("insert into prj.", "update prj.", "delete from prj."):
            self.assertNotIn(forbidden, lowered)

    def test_initial_binding_scope_is_water_and_sewer_only(self):
        self.assertIn('(\"WATER\", \"WATER\", 2)', self.sync_script)
        self.assertIn('(\"SEWERAGE\", \"SEWER\", 2)', self.sync_script)
        self.assertNotIn('(\"ROAD\", \"ROAD\", 2)', self.sync_script)
        self.assertIn('"WATER": (11, 2, 9, 0)', self.sync_script)
        self.assertIn('"SEWER": (10, 2, 0, 8)', self.sync_script)

    def test_binding_sync_is_exactly_targeted_and_transaction_rehearsed(self):
        self.assertIn("SYNC_GIS_CATALOG_BINDINGS:{group_code}:{db_alias}", self.sync_script)
        self.assertIn("commit=False", self.sync_script)
        self.assertIn("commit=True", self.sync_script)
        self.assertIn("pg_advisory_xact_lock", self.sync_script)
        self.assertIn("lock_timeout", self.sync_script)
        self.assertIn("statement_timeout", self.sync_script)

    def test_binding_sync_does_not_mutate_business_catalog_or_projects(self):
        lowered = self.sync_script.lower()
        for forbidden in (
            "insert into prj.",
            "update prj.",
            "delete from prj.",
            "insert into catalog.",
            "update catalog.",
            "delete from catalog.",
            "insert into gis.project_profile",
            "delete from gis.project_profile",
            "drop ",
            "truncate ",
        ):
            self.assertNotIn(forbidden, lowered)


if __name__ == "__main__":
    unittest.main()
