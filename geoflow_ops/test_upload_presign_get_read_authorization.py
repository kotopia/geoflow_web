from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.test import RequestFactory, SimpleTestCase

from geoflow_ops.views_uploads import (
    _authorize_attachment_read,
    _request_has_any_perm,
    presign_get,
)


class UploadPresignGetReadAuthorizationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, *, gf_cache=None, gf_perms=None, perms=None):
        return SimpleNamespace(
            _gf_perms_cache=gf_cache,
            session={"gf_perms": gf_perms, "perms": perms},
        )

    def _attachment(self, entity_type):
        return SimpleNamespace(entity_type=entity_type, entity_id=uuid4())

    def test_request_has_permission_from_gf_perms_list(self):
        request = self._request(gf_perms=["directory.view"])

        self.assertTrue(_request_has_any_perm(request, "directory.view"))

    def test_request_has_permission_from_perms_list(self):
        request = self._request(perms=["contracts.view"])

        self.assertTrue(_request_has_any_perm(request, "contracts.view"))

    def test_request_has_truthy_permission_from_dict(self):
        request = self._request(gf_cache={"directory.view": True})

        self.assertTrue(_request_has_any_perm(request, "directory.view"))

    def test_request_without_permission_returns_false(self):
        request = self._request(gf_perms=[], perms=[])

        self.assertFalse(_request_has_any_perm(request, "directory.view"))

    def test_employee_read_requires_directory_view(self):
        attachment = self._attachment("employee")

        self.assertFalse(
            _authorize_attachment_read(self._request(), "tenant_test", attachment)
        )
        self.assertTrue(
            _authorize_attachment_read(
                self._request(perms=["directory.view"]),
                "tenant_test",
                attachment,
            )
        )

    def test_contract_read_requires_contracts_view(self):
        attachment = self._attachment("contract")

        self.assertFalse(
            _authorize_attachment_read(self._request(), "tenant_test", attachment)
        )
        self.assertTrue(
            _authorize_attachment_read(
                self._request(gf_perms=["contracts.view"]),
                "tenant_test",
                attachment,
            )
        )

    def test_event_read_uses_source_scope_permission(self):
        attachment = self._attachment("event")
        cases = (
            ("employee", None, False),
            ("employee", "directory.view", True),
            ("contract", None, False),
            ("contract", "contracts.view", True),
            ("orgunit", "directory.view", False),
            ("unknown", "contracts.view", False),
        )

        for scope_type, permission, expected in cases:
            with self.subTest(scope_type=scope_type, permission=permission):
                with patch("geoflow_ops.models.ProcessEvent") as process_event:
                    process_event.objects.using.return_value.filter.return_value.only.return_value.first.return_value = (
                        SimpleNamespace(scope_type=scope_type)
                    )
                    request = self._request(
                        perms=[permission] if permission else []
                    )

                    self.assertEqual(
                        _authorize_attachment_read(
                            request, "tenant_test", attachment
                        ),
                        expected,
                    )

    def test_unsupported_entities_fail_closed(self):
        request = self._request(
            gf_perms=["directory.view", "contracts.view"]
        )

        for entity_type in ("orgunit", "project", "unknown"):
            with self.subTest(entity_type=entity_type):
                self.assertFalse(
                    _authorize_attachment_read(
                        request,
                        "tenant_test",
                        self._attachment(entity_type),
                    )
                )

    def test_presign_get_denial_returns_403_without_s3_call(self):
        request = self.factory.get("/api/uploads/presign-get/test/")
        request.user = SimpleNamespace(is_authenticated=True)
        request.session = {}
        attachment = SimpleNamespace(deleted_at=None)

        with (
            patch("geoflow_ops.views_uploads._alias", return_value="tenant_test"),
            patch("geoflow_ops.views_uploads.Attachment") as attachment_model,
            patch(
                "geoflow_ops.views_uploads._resolve_attachment_entity",
                return_value=True,
            ),
            patch(
                "geoflow_ops.views_uploads._authorize_attachment_read",
                return_value=False,
            ),
            patch(
                "geoflow_ops.views_uploads.generate_presigned_get_url"
            ) as generate_url,
        ):
            attachment_model.objects.using.return_value.get.return_value = attachment

            response = presign_get(request, uuid4())

        self.assertEqual(response.status_code, 403)
        self.assertJSONEqual(response.content, {"error": "Forbidden"})
        generate_url.assert_not_called()
