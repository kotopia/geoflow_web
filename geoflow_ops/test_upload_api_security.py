from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class UploadApiSecurityStaticTests(unittest.TestCase):
    def test_direct_upload_surface_is_fail_closed(self):
        source = (ROOT / "views_uploads.py").read_text(encoding="utf-8")
        for pair in (
            '("employee", "photo")',
            '("employee", "photo_thumb")',
            '("employee", "doc")',
            '("event", "doc")',
        ):
            self.assertIn(pair, source)
        self.assertNotIn('(\"contract\", \"', source)
        self.assertNotIn('(\"orgunit\", \"', source)

    def test_commit_authorizes_and_heads_before_db_insert(self):
        source = (ROOT / "views_uploads.py").read_text(encoding="utf-8")
        auth_pos = source.index("authorize_attachment_write(request, alias, entity_type, entity_id)", source.index("def commit"))
        head_pos = source.index("head_private_object(object_key)", source.index("def commit"))
        save_pos = source.index("attachment.save(using=alias)", source.index("def commit"))
        self.assertLess(auth_pos, head_pos)
        self.assertLess(head_pos, save_pos)
        self.assertIn("transaction.atomic(using=alias)", source)
        self.assertIn("Attachment already committed", source)

    def test_download_mode_is_allowlisted(self):
        source = (ROOT / "views_uploads.py").read_text(encoding="utf-8")
        self.assertIn('if mode not in {"inline", "download"}:', source)
        s3_source = (ROOT / "services" / "s3_service.py").read_text(encoding="utf-8")
        self.assertIn('disposition not in (None, "inline", "attachment")', s3_source)
        self.assertIn("[\\r\\n", s3_source)
