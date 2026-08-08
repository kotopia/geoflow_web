from inspect import getsource

from django.test import SimpleTestCase

from geoflow_ops.event_security_views import event_list
from geoflow_ops import views_events
from geoflow_ops import views_uploads


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
