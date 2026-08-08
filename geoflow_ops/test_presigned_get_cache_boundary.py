from inspect import getsource

from django.test import SimpleTestCase

from geoflow_ops.upload_guard_views import presign_get


class PresignedGetCacheBoundaryTests(SimpleTestCase):
    def test_signed_download_url_response_is_never_cached(self):
        source = getsource(presign_get)
        self.assertIn("@never_cache", source)
        self.assertIn("@login_required", source)
        self.assertIn("@require_GET", source)
