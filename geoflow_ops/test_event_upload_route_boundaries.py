from inspect import getsource
from types import SimpleNamespace

from django.test import SimpleTestCase

from geoflow_ops.event_security_views import event_list
from geoflow_ops import views_events
from geoflow_ops import views_uploads
from geoflow_ops.upload_guard_views import _effective_inline_mime


class EventUploadRouteBoundaryTests(SimpleTestCase):
    def test_event_list_is_never_cached_authenticated_get(self):
        source = getsource(event_list)
        self.assertIn("@never_cache", source)
        self.assertIn("@login_required", source)
        self.assertIn("@require_GET", source)
        self.assertIn("require_tenant_context(request)", source)

    def test_event_mutations_remain_post_only(self):
        for view in (
            views_events.create_event,
            views_events.update_event,
            views_events.delete_event,
        ):
            with self.subTest(view=view.__name__):
                source = getsource(view)
                self.assertIn("@login_required", source)
                self.assertIn("@require_POST", source)

    def test_attachment_delete_remains_delete_only(self):
        source = getsource(views_uploads.delete_attachment)
        self.assertIn("@login_required", source)
        self.assertIn('@require_http_methods(["DELETE"])', source)

    def test_legacy_generic_pdf_mime_is_inferred_for_inline_preview(self):
        for mime_type in (None, "", "application/octet-stream", "application/force-download"):
            with self.subTest(mime_type=mime_type):
                attachment = SimpleNamespace(
                    mime_type=mime_type,
                    original_name="기존계약서.PDF",
                    object_key="tenant/events/legacy-document.bin",
                )
                self.assertEqual(_effective_inline_mime(attachment), "application/pdf")

    def test_specific_unsafe_mime_is_never_overridden_by_filename(self):
        attachment = SimpleNamespace(
            mime_type="text/html",
            original_name="renamed.pdf",
            object_key="tenant/events/renamed.pdf",
        )
        self.assertEqual(_effective_inline_mime(attachment), "")

    def test_non_preview_document_stays_download_only(self):
        attachment = SimpleNamespace(
            mime_type="application/octet-stream",
            original_name="보고서.xlsx",
            object_key="tenant/events/report.xlsx",
        )
        self.assertEqual(_effective_inline_mime(attachment), "")
