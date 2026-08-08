from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class AttachmentContentGuardStaticTests(unittest.TestCase):
    def test_active_event_document_types_are_blocked(self):
        source = (ROOT / "upload_guard_views.py").read_text(encoding="utf-8")
        for value in (
            '"html"', '"svg"', '"js"',
            '"text/html"', '"image/svg+xml"', '"application/javascript"',
        ):
            self.assertIn(value, source)
        self.assertIn('status=415', source)
        self.assertIn('(entity_type, purpose) == ("event", "doc")', source)

    def test_inline_preview_is_allowlisted_and_other_types_download(self):
        source = (ROOT / "upload_guard_views.py").read_text(encoding="utf-8")
        for mime in (
            '"application/pdf"',
            '"image/jpeg"',
            '"image/png"',
            '"image/webp"',
            '"text/plain"',
        ):
            self.assertIn(mime, source)
        self.assertIn('mime_type in INLINE_SAFE_MIME_TYPES', source)
        self.assertIn('response_type = mime_type if inline_allowed else "application/octet-stream"', source)
        self.assertIn('"effective_mode": "inline" if inline_allowed else "download"', source)

    def test_presign_get_route_uses_guard(self):
        urls = (ROOT / "urls.py").read_text(encoding="utf-8")
        self.assertIn(
            'path("api/uploads/presign-get/<uuid:attachment_id>/", upload_guard_views.presign_get',
            urls,
        )


if __name__ == "__main__":
    unittest.main()
