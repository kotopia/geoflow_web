from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "iroomsng-public-upload-path-diagnostic.yml"


class IroomsngPublicUploadPathContractTests(TestCase):
    def _text(self) -> str:
        return WORKFLOW.read_text()

    def test_probe_never_sends_a_file_or_s3_request(self):
        text = self._text()
        self.assertIn("https://iroomsng.kr/api/upload-photo/", text)
        self.assertIn("--request POST", text)
        self.assertIn("layer_name=diagnostic", text)
        self.assertIn("object_id=diagnostic", text)
        for forbidden in (
            "--form",
            "-F ",
            "@/",
            "boto3",
            "put_object",
            "upload_file",
            "aws s3",
        ):
            self.assertNotIn(forbidden, text)

    def test_400_is_the_application_boundary_signal_and_502_is_upstream_signal(self):
        text = self._text()
        self.assertIn('[ "$upload_boundary_code" = "400" ]', text)
        self.assertIn("iroomsng_upload_route_reaches_application=yes", text)
        self.assertIn('[ "$upload_boundary_code" = "502" ]', text)
        self.assertIn("iroomsng_upload_route_upstream_502_without_file=yes", text)
        self.assertIn("iroomsng_public_upload_path_diagnostic_complete=yes", text)

    def test_workflow_has_no_production_environment_or_repository_write_permission(self):
        text = self._text()
        self.assertNotIn("environment: production", text)
        self.assertIn("permissions:\n  contents: read", text)
        self.assertNotIn("contents: write", text)
        self.assertNotIn("actions: write", text)
