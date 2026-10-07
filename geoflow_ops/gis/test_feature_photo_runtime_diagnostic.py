from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[2]


class FeaturePhotoRuntimeDiagnosticContractTests(TestCase):
    def test_diagnostic_is_bounded_and_read_only(self):
        script = (ROOT / "scripts/ops/diagnose_gis_photo_api_503.py").read_text()
        workflow = (ROOT / ".github/workflows/gis-photo-api-503-diagnostic.yml").read_text()
        self.assertIn('PROJECT_ID = "6ba9dd5d-0189-4cda-854a-afa0caf06a27"', script)
        self.assertIn('PHYSICAL_NAME = "wtl_pipe_ps"', script)
        self.assertIn("tenant_cursor(config.group_id, write=False)", script)
        self.assertNotIn("INSERT INTO", script)
        self.assertNotIn("UPDATE gis.", script)
        self.assertNotIn("DELETE FROM", script)
        self.assertIn("default_transaction_read_only=on", workflow)
        self.assertIn("2026-10-07 08:22:30 UTC", workflow)
        self.assertIn("gis_photo_diag_operating_sha", workflow)
