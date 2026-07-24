import json
from types import SimpleNamespace
from unittest.mock import Mock, patch

from django.test import RequestFactory, SimpleTestCase

from geoflow_ops.views_events import (
    create_event,
    delete_event,
    list_events,
    update_event,
)


class PermissionStagePassed(Exception):
    pass


class EventWritePermissionTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _user(self):
        return SimpleNamespace(is_authenticated=True, username="", email="")

    def _create_request(self, permissions):
        request = self.factory.post(
            "/api/events/create/",
            data=json.dumps(
                {
                    "scope_type": "contract",
                    "scope_id": "scope-key",
                    "stage": "stage",
                    "event_type": "event-type",
                }
            ),
            content_type="application/json",
        )
        request.user = self._user()
        request.session = {"gf_perms": permissions}
        return request

    def _event_request(self, path, permissions, payload=None):
        request = self.factory.post(
            path,
            data=json.dumps(payload or {}),
            content_type="application/json",
        )
        request.user = self._user()
        request.session = {"gf_perms": permissions}
        return request

    @patch("geoflow_ops.views_events.ProcessEvent")
    @patch("geoflow_ops.views_events._alias")
    @patch("geoflow_ops.views_events.UUID", return_value="scope-key")
    def test_contract_create_without_contracts_edit_returns_403(
        self, uuid_mock, alias_mock, event_model_mock
    ):
        response = create_event(self._create_request([]))

        self.assertEqual(response.status_code, 403)
        alias_mock.assert_not_called()
        event_model_mock.assert_not_called()

    @patch("geoflow_ops.views_events._alias")
    @patch("geoflow_ops.views_events.UUID", return_value="scope-key")
    def test_contract_create_with_only_contracts_view_returns_403(
        self, uuid_mock, alias_mock
    ):
        response = create_event(self._create_request(["contracts.view"]))

        self.assertEqual(response.status_code, 403)
        alias_mock.assert_not_called()

    @patch("geoflow_ops.views_events._alias")
    @patch("geoflow_ops.views_events.UUID", return_value="scope-key")
    def test_contract_create_with_only_contracts_create_returns_403(
        self, uuid_mock, alias_mock
    ):
        response = create_event(self._create_request(["contracts.create"]))

        self.assertEqual(response.status_code, 403)
        alias_mock.assert_not_called()

    @patch(
        "geoflow_ops.views_events._alias",
        side_effect=PermissionStagePassed,
    )
    @patch("geoflow_ops.views_events.UUID", return_value="scope-key")
    def test_contract_create_with_contracts_edit_passes_permission_stage(
        self, uuid_mock, alias_mock
    ):
        with self.assertRaises(PermissionStagePassed):
            create_event(self._create_request(["contracts.edit"]))

        alias_mock.assert_called_once()

    @patch("geoflow_ops.views_events.ProcessEvent")
    @patch("geoflow_ops.views_events._alias", return_value="tenant")
    def test_update_uses_stored_contract_scope_not_payload_scope(
        self, alias_mock, event_model_mock
    ):
        event = SimpleNamespace(scope_type="contract", save=Mock())
        event_model_mock.objects.using.return_value.get.return_value = event
        request = self._event_request(
            "/api/events/update/",
            [],
            {"scope_type": "employee", "title": "changed"},
        )

        response = update_event(request, event_id="event-key")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(hasattr(event, "title"))
        event.save.assert_not_called()

    @patch("geoflow_ops.views_events.ProcessEvent")
    @patch("geoflow_ops.views_events._alias", return_value="tenant")
    def test_update_denial_occurs_before_save(
        self, alias_mock, event_model_mock
    ):
        event = SimpleNamespace(scope_type="contract", save=Mock())
        event_model_mock.objects.using.return_value.get.return_value = event
        request = self._event_request(
            "/api/events/update/",
            ["contracts.view"],
            {"title": "changed"},
        )

        response = update_event(request, event_id="event-key")

        self.assertEqual(response.status_code, 403)
        self.assertFalse(hasattr(event, "title"))
        event.save.assert_not_called()

    @patch("geoflow_ops.views_events.ProcessEventAttachment")
    @patch("geoflow_ops.views_events.ProcessEvent")
    @patch("geoflow_ops.views_events._alias", return_value="tenant")
    def test_delete_denial_occurs_before_link_or_event_delete(
        self, alias_mock, event_model_mock, link_model_mock
    ):
        event = SimpleNamespace(scope_type="contract", delete=Mock())
        event_model_mock.objects.using.return_value.get.return_value = event
        request = self._event_request(
            "/api/events/delete/",
            ["contracts.create"],
        )

        response = delete_event(request, event_id="event-key")

        self.assertEqual(response.status_code, 403)
        link_model_mock.objects.using.assert_not_called()
        event.delete.assert_not_called()

    @patch("geoflow_ops.views_events.ProcessEvent")
    @patch("geoflow_ops.views_events._alias")
    @patch("geoflow_ops.views_events.UUID", return_value="scope-key")
    def test_denied_create_does_not_construct_or_save_event(
        self, uuid_mock, alias_mock, event_model_mock
    ):
        response = create_event(
            self._create_request(["contracts.view", "contracts.create"])
        )

        self.assertEqual(response.status_code, 403)
        alias_mock.assert_not_called()
        event_model_mock.assert_not_called()

    @patch(
        "geoflow_ops.views_events._alias",
        side_effect=PermissionStagePassed,
    )
    @patch("geoflow_ops.views_events._authorize_event_write")
    @patch("geoflow_ops.views_events.UUID", return_value="scope-key")
    def test_event_list_read_does_not_use_write_authorization(
        self, uuid_mock, authorize_mock, alias_mock
    ):
        request = self.factory.get(
            "/api/events/list/",
            {"scope_type": "contract", "scope_id": "scope-key"},
        )
        request.user = self._user()

        with self.assertRaises(PermissionStagePassed):
            list_events(request)

        authorize_mock.assert_not_called()
        alias_mock.assert_called_once_with(request)
