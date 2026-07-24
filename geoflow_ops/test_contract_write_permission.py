from types import SimpleNamespace
from unittest.mock import patch

from django.test import RequestFactory, SimpleTestCase

from geoflow_ops.views_contracts import contract_detail_page


class PermissionStagePassed(Exception):
    pass


class ContractWritePermissionTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    def _request(self, method, permissions):
        request = getattr(self.factory, method.lower())("/contracts/detail/")
        request.user = SimpleNamespace(is_authenticated=True)
        request.session = {"gf_perms": permissions}
        return request

    @patch(
        "geoflow_ops.views_contracts._alias",
        side_effect=PermissionStagePassed,
    )
    def test_contract_detail_get_remains_allowed_with_contracts_view(self, alias_mock):
        request = self._request("GET", ["contracts.view"])

        with self.assertRaises(PermissionStagePassed):
            contract_detail_page(request, pk="contract-key")

        alias_mock.assert_called_once_with(request)

    @patch("geoflow_ops.views_contracts._alias")
    @patch("geoflow_ops.views_contracts.get_object_or_404")
    @patch("geoflow_ops.views_contracts.ContractForm")
    def test_contract_detail_post_without_contracts_edit_returns_403(
        self,
        form_mock,
        get_object_mock,
        alias_mock,
    ):
        request = self._request("POST", ["contracts.view"])

        response = contract_detail_page(request, pk="contract-key")

        self.assertEqual(response.status_code, 403)
        alias_mock.assert_not_called()
        get_object_mock.assert_not_called()
        form_mock.assert_not_called()

    @patch("geoflow_ops.views_contracts._alias")
    def test_contracts_create_does_not_authorize_contract_detail_post(
        self,
        alias_mock,
    ):
        request = self._request(
            "POST",
            ["contracts.view", "contracts.create"],
        )

        response = contract_detail_page(request, pk="contract-key")

        self.assertEqual(response.status_code, 403)
        alias_mock.assert_not_called()

    @patch("geoflow_ops.views_contracts._alias")
    def test_contracts_view_does_not_authorize_contract_detail_post(
        self,
        alias_mock,
    ):
        request = self._request("POST", ["contracts.view"])

        response = contract_detail_page(request, pk="contract-key")

        self.assertEqual(response.status_code, 403)
        alias_mock.assert_not_called()

    @patch(
        "geoflow_ops.views_contracts._alias",
        side_effect=PermissionStagePassed,
    )
    def test_contracts_edit_passes_contract_detail_post_permission_stage(
        self,
        alias_mock,
    ):
        request = self._request(
            "POST",
            ["contracts.view", "contracts.edit"],
        )

        with self.assertRaises(PermissionStagePassed):
            contract_detail_page(request, pk="contract-key")

        alias_mock.assert_called_once_with(request)

    @patch("geoflow_ops.views_contracts._alias")
    @patch("geoflow_ops.views_contracts.get_object_or_404")
    @patch("geoflow_ops.views_contracts.ContractForm")
    def test_denied_post_does_not_reach_form_or_database_work(
        self,
        form_mock,
        get_object_mock,
        alias_mock,
    ):
        request = self._request(
            "POST",
            ["contracts.view", "contracts.create"],
        )

        response = contract_detail_page(request, pk="contract-key")

        self.assertEqual(response.status_code, 403)
        alias_mock.assert_not_called()
        get_object_mock.assert_not_called()
        form_mock.assert_not_called()
