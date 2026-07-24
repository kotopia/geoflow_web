from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

from geoflow_ops.views_uploads import (
    _authorize_attachment_delete,
    delete_attachment,
)


class AttachmentDeleteAuthorizationTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, permissions, payload_scope=None):
        request = self.factory.delete(
            "/api/uploads/delete/attachment-key/",
            data={"scope_type": payload_scope} if payload_scope else {},
        )
        request.user = SimpleNamespace(
            is_authenticated=True,
            username="test-user",
        )
        request.session = {"gf_perms": permissions}
        return request

    def _attachment(self, entity_type):
        return SimpleNamespace(
            id="stored-attachment-key",
            entity_type=entity_type,
            entity_id="stored-entity-key",
            deleted_at=None,
            deleted_by=None,
            is_deleted=False,
            save=Mock(),
        )

    def test_employee_attachment_delete_requires_directory_edit(self):
        attachment = self._attachment("employee")

        self.assertFalse(
            _authorize_attachment_delete(self._request([]), "tenant", attachment)
        )
        self.assertTrue(
            _authorize_attachment_delete(
                self._request(["directory.edit"]),
                "tenant",
                attachment,
            )
        )

    @patch("geoflow_ops.models.ProcessEvent")
    def test_employee_scoped_event_delete_requires_directory_edit(
        self,
        event_model_mock,
    ):
        attachment = self._attachment("event")
        event_model_mock.objects.using.return_value.filter.return_value.only.return_value.first.return_value = (
            SimpleNamespace(scope_type="employee")
        )

        self.assertFalse(
            _authorize_attachment_delete(self._request([]), "tenant", attachment)
        )
        self.assertTrue(
            _authorize_attachment_delete(
                self._request(["directory.edit"]),
                "tenant",
                attachment,
            )
        )

    def test_contract_attachment_delete_requires_contracts_edit(self):
        attachment = self._attachment("contract")

        self.assertFalse(
            _authorize_attachment_delete(self._request([]), "tenant", attachment)
        )
        self.assertTrue(
            _authorize_attachment_delete(
                self._request(["contracts.edit"]),
                "tenant",
                attachment,
            )
        )

    @patch("geoflow_ops.models.ProcessEvent")
    def test_contract_scoped_event_delete_requires_contracts_edit(
        self,
        event_model_mock,
    ):
        attachment = self._attachment("event")
        event_model_mock.objects.using.return_value.filter.return_value.only.return_value.first.return_value = (
            SimpleNamespace(scope_type="contract")
        )

        self.assertFalse(
            _authorize_attachment_delete(self._request([]), "tenant", attachment)
        )
        self.assertTrue(
            _authorize_attachment_delete(
                self._request(["contracts.edit"]),
                "tenant",
                attachment,
            )
        )

    def test_contracts_view_does_not_authorize_contract_attachment_delete(self):
        self.assertFalse(
            _authorize_attachment_delete(
                self._request(["contracts.view"]),
                "tenant",
                self._attachment("contract"),
            )
        )

    def test_contracts_create_does_not_authorize_contract_attachment_delete(self):
        self.assertFalse(
            _authorize_attachment_delete(
                self._request(["contracts.create"]),
                "tenant",
                self._attachment("contract"),
            )
        )

    def test_orgunit_project_and_unknown_attachments_fail_closed(self):
        request = self._request(["directory.edit", "contracts.edit"])

        for entity_type in ("orgunit", "project", "unknown"):
            with self.subTest(entity_type=entity_type):
                self.assertFalse(
                    _authorize_attachment_delete(
                        request,
                        "tenant",
                        self._attachment(entity_type),
                    )
                )

    @patch("geoflow_ops.views_uploads.Attachment")
    @patch(
        "geoflow_ops.views_uploads._resolve_attachment_entity",
        return_value=True,
    )
    @patch("geoflow_ops.views_uploads._alias", return_value="tenant")
    def test_denied_delete_returns_403_before_mutation(
        self,
        alias_mock,
        resolve_mock,
        attachment_model_mock,
    ):
        attachment = self._attachment("contract")
        attachment_model_mock.objects.using.return_value.get.return_value = attachment
        request = self._request(["contracts.view"])
        session_before = dict(request.session)

        response = delete_attachment(request, attachment_id="attachment-key")

        self.assertEqual(response.status_code, 403)
        attachment.save.assert_not_called()
        self.assertEqual(request.session, session_before)

    @patch("geoflow_ops.views_uploads.generate_presigned_put_url")
    @patch("geoflow_ops.views_uploads.generate_presigned_get_url")
    @patch("geoflow_ops.views_uploads.Attachment")
    @patch(
        "geoflow_ops.views_uploads._resolve_attachment_entity",
        return_value=True,
    )
    @patch("geoflow_ops.views_uploads._alias", return_value="tenant")
    def test_denied_delete_does_not_call_s3(
        self,
        alias_mock,
        resolve_mock,
        attachment_model_mock,
        presigned_get_mock,
        presigned_put_mock,
    ):
        attachment = self._attachment("contract")
        attachment_model_mock.objects.using.return_value.get.return_value = attachment

        response = delete_attachment(
            self._request(["contracts.create"]),
            attachment_id="attachment-key",
        )

        self.assertEqual(response.status_code, 403)
        presigned_get_mock.assert_not_called()
        presigned_put_mock.assert_not_called()

    @patch("geoflow_ops.views_uploads.Attachment")
    @patch(
        "geoflow_ops.views_uploads._resolve_attachment_entity",
        return_value=True,
    )
    @patch("geoflow_ops.views_uploads._alias", return_value="tenant")
    def test_allowed_delete_reaches_existing_mutation_stage(
        self,
        alias_mock,
        resolve_mock,
        attachment_model_mock,
    ):
        attachment = self._attachment("contract")
        attachment_model_mock.objects.using.return_value.get.return_value = attachment

        response = delete_attachment(
            self._request(["contracts.edit"]),
            attachment_id="attachment-key",
        )

        self.assertEqual(response.status_code, 200)
        self.assertTrue(attachment.is_deleted)
        self.assertIsNotNone(attachment.deleted_at)
        attachment.save.assert_called_once_with(using="tenant")

    @patch("geoflow_ops.models.ProcessEvent")
    def test_delete_authorization_uses_stored_event_scope_not_request_payload(
        self,
        event_model_mock,
    ):
        attachment = self._attachment("event")
        event_model_mock.objects.using.return_value.filter.return_value.only.return_value.first.return_value = (
            SimpleNamespace(scope_type="contract")
        )

        self.assertFalse(
            _authorize_attachment_delete(
                self._request(["directory.edit"], payload_scope="employee"),
                "tenant",
                attachment,
            )
        )
        self.assertTrue(
            _authorize_attachment_delete(
                self._request(["contracts.edit"], payload_scope="employee"),
                "tenant",
                attachment,
            )
        )

    @patch("geoflow_ops.models.ProcessEvent")
    def test_missing_event_scope_fails_closed(self, event_model_mock):
        attachment = self._attachment("event")
        event_model_mock.objects.using.return_value.filter.return_value.only.return_value.first.return_value = None

        self.assertFalse(
            _authorize_attachment_delete(
                self._request(["directory.edit", "contracts.edit"]),
                "tenant",
                attachment,
            )
        )
