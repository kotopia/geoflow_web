from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class UploadSizeGuardStaticTests(unittest.TestCase):
    def test_default_limits_are_bounded(self):
        source = (ROOT / "upload_guard_views.py").read_text(encoding="utf-8")
        self.assertIn('(\"employee\", \"photo\")', source)
        self.assertIn('15 * 1024 * 1024', source)
        self.assertIn('(\"employee\", \"photo_thumb\")', source)
        self.assertIn('2 * 1024 * 1024', source)
        self.assertIn('(\"employee\", \"doc\")', source)
        self.assertIn('25 * 1024 * 1024', source)
        self.assertIn('(\"event\", \"doc\")', source)
        self.assertIn('100 * 1024 * 1024', source)
        self.assertIn('status=413', source)

    def test_guard_runs_before_upload_views(self):
        source = (ROOT / "upload_guard_views.py").read_text(encoding="utf-8")
        for name in ("presign_put", "commit"):
            start = source.index(f"def {name}(request):")
            block = source[start:]
            self.assertLess(block.index("_enforce_size(request)"), block.index(f"views_uploads.{name}(request)"))
        self.assertIn("require_tenant_context(request)", source)
