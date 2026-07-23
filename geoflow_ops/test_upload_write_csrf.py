from uuid import uuid4

from django.middleware.csrf import CsrfViewMiddleware
from django.test import RequestFactory, SimpleTestCase
from django.urls import resolve


class UploadWriteCsrfTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()
        self.middleware = CsrfViewMiddleware(lambda request: None)

    def _csrf_process_view(
        self,
        path,
        method="post",
        content_type="application/json",
    ):
        if method.lower() == "get":
            request = self.factory.get(path)
        else:
            request = self.factory.generic(
                method.upper(),
                path,
                data=b"{}",
                content_type=content_type,
            )

        match = resolve(path)
        response = self.middleware.process_view(
            request,
            match.func,
            match.args,
            match.kwargs,
        )
        return response

    def test_presign_put_without_csrf_token_returns_403(self):
        response = self._csrf_process_view("/api/uploads/presign-put/")

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 403)

    def test_commit_without_csrf_token_returns_403(self):
        response = self._csrf_process_view("/api/uploads/commit/")

        self.assertIsNotNone(response)
        self.assertEqual(response.status_code, 403)

    def test_presign_put_resolved_view_is_not_csrf_exempt(self):
        view_func = resolve("/api/uploads/presign-put/").func

        self.assertFalse(getattr(view_func, "csrf_exempt", False))

    def test_commit_resolved_view_is_not_csrf_exempt(self):
        view_func = resolve("/api/uploads/commit/").func

        self.assertFalse(getattr(view_func, "csrf_exempt", False))

    def test_delete_resolved_view_remains_csrf_exempt(self):
        path = f"/api/uploads/delete/{uuid4()}/"
        view_func = resolve(path).func

        self.assertTrue(getattr(view_func, "csrf_exempt", False))

    def test_presign_get_safe_method_is_not_blocked_by_csrf(self):
        path = f"/api/uploads/presign-get/{uuid4()}/"

        response = self._csrf_process_view(path, method="get")

        self.assertIsNone(response)
