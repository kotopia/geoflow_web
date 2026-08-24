import json
import os
from types import SimpleNamespace
from unittest.mock import patch

from django.http import Http404
from django.test import RequestFactory, SimpleTestCase

from geoflow_ops import temp_contract_list_api as api


class TempContractListApiTests(SimpleTestCase):
    def setUp(self):
        self.factory = RequestFactory()

    @patch.dict(os.environ, {"TEMP_CONTRACT_LIST_API_ENABLED": "0"}, clear=False)
    def test_disabled_endpoint_is_hidden(self):
        request = self.factory.get("/api/temp/contracts/")
        with self.assertRaises(Http404):
            api.contract_list(request)

    @patch.dict(
        os.environ,
        {
            "TEMP_CONTRACT_LIST_API_ENABLED": "1",
            "TEMP_CONTRACT_LIST_API_KEY": "expected-key",
        },
        clear=False,
    )
    def test_missing_key_is_forbidden(self):
        request = self.factory.get("/api/temp/contracts/")
        response = api.contract_list(request)
        self.assertEqual(response.status_code, 403)
        self.assertEqual(json.loads(response.content), {"detail": "Forbidden."})

    def test_contract_payload_contains_flat_project_fields_and_full_project_list(self):
        client = SimpleNamespace(name="발주처")
        sub_client = SimpleNamespace(name="하도급처")
        org_unit = SimpleNamespace(name="본사")
        contract = SimpleNamespace(
            id="contract-1",
            legacy_id=10,
            code="C-001",
            name="계약명",
            start_date="2026-01-01",
            end_date="2026-12-31",
            amount=123456,
            status="진행",
            kind="일반",
            division="GIS",
            client_id="client-1",
            client=client,
            sub_client_id="sub-1",
            sub_client=sub_client,
            org_unit_id="org-1",
            org_unit=org_unit,
            description="비고",
            ext={"region": "충남"},
            created_at="2026-01-01T00:00:00+09:00",
            updated_at="2026-08-24T00:00:00+09:00",
        )
        projects = [
            SimpleNamespace(
                id="project-1",
                contract_id="contract-1",
                code="P-001",
                name="프로젝트1",
                start_date="2026-01-01",
                end_date="2026-06-30",
                status="진행",
                description="",
                org_unit_id="org-1",
                ext={},
                created_at=None,
                updated_at=None,
            ),
            SimpleNamespace(
                id="project-2",
                contract_id="contract-1",
                code="P-002",
                name="프로젝트2",
                start_date="2026-07-01",
                end_date="2026-12-31",
                status="대기",
                description="",
                org_unit_id="org-1",
                ext={},
                created_at=None,
                updated_at=None,
            ),
        ]

        payload = api._contract_payload(contract, projects)

        self.assertEqual(payload["contract_code"], "C-001")
        self.assertEqual(payload["project_code"], "P-001")
        self.assertEqual(payload["project_codes"], ["P-001", "P-002"])
        self.assertEqual(payload["client_name"], "발주처")
        self.assertEqual(payload["sub_client_name"], "하도급처")
        self.assertEqual(payload["org_unit_name"], "본사")
        self.assertEqual(len(payload["projects"]), 2)
        self.assertEqual(payload["projects"][1]["code"], "P-002")
