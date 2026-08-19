from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from django.test import SimpleTestCase

from geoflow_ops.services.workflow_state import (
    fallback_stage_for_contract_status,
    major_phase_for_stage,
)


ROOT = Path(__file__).resolve().parent


class ContractWorkflowPhaseTests(SimpleTestCase):
    def test_major_contract_flow_groups_detail_stages_without_replacing_them(self):
        self.assertEqual(major_phase_for_stage("pre_contract"), ("contract", "계약(전)"))
        self.assertEqual(major_phase_for_stage("contract"), ("contract", "계약(전)"))
        self.assertEqual(major_phase_for_stage("kickoff"), ("execution", "수행(진행)"))
        self.assertEqual(major_phase_for_stage("execution"), ("execution", "수행(진행)"))
        self.assertEqual(major_phase_for_stage("inspection"), ("execution", "수행(진행)"))
        self.assertEqual(major_phase_for_stage("closeout"), ("closeout", "준공"))
        self.assertEqual(major_phase_for_stage("billing"), ("closeout", "준공"))

    def test_contract_status_is_legacy_fallback_not_workflow_source_of_truth(self):
        self.assertEqual(fallback_stage_for_contract_status("planned"), "pre_contract")
        self.assertEqual(fallback_stage_for_contract_status("complete"), "closeout")
        self.assertEqual(fallback_stage_for_contract_status("active"), "execution")

    def test_contract_templates_show_four_step_event_driven_workflow(self):
        listing = (ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_list.html").read_text(encoding="utf-8")
        detail = (ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_detail.html").read_text(encoding="utf-8")
        self.assertIn("업무단계", listing)
        self.assertNotIn("운영상태", listing)
        self.assertIn("현재 업무단계", detail)
        self.assertIn("단계 기준", detail)
        self.assertNotIn("운영상태", detail)
        for label in ("1. 계약", "2. 진행", "3. 준공", "4. 완료"):
            self.assertIn(label, detail)
        self.assertIn("준공 완료", detail)


class SharedEventHandoffContractTests(SimpleTestCase):
    def test_shared_event_ledger_keeps_contract_and_project_lineage(self):
        source = (ROOT / "views_events.py").read_text(encoding="utf-8")
        self.assertIn('scope_type="project"', (ROOT / "views_execution.py").read_text(encoding="utf-8"))
        self.assertIn("contract_id=contract_id", source)
        self.assertIn("project_id=project_id", source)

    def test_inspection_request_task_completion_creates_management_handoff(self):
        source = (ROOT / "views_execution.py").read_text(encoding="utf-8")
        self.assertIn("_is_inspection_request_task", source)
        self.assertIn("_create_inspection_handoff_event", source)
        self.assertIn('"handoff": "business_to_management"', source)
        self.assertIn("route_project_inspection_request_to_management", source)
        self.assertIn('event_type="inspection_request"', source)

    def test_department_routing_is_scoped_to_contract_company(self):
        source = (ROOT / "services" / "department_routing.py").read_text(encoding="utf-8")
        self.assertIn("scope_org_unit_id", source)
        self.assertIn("org_unit_id=%s::uuid", source)
        self.assertIn('MANAGEMENT_DEPARTMENT_NAME = "관리부"', source)
        self.assertIn('event_type == "kickoff"', source)

    def test_event_status_is_internal_only_and_new_events_open(self):
        modal = (ROOT / "templates" / "geoflow_ops" / "events" / "_event_modal.html").read_text(encoding="utf-8")
        event_views = (ROOT / "views_events.py").read_text(encoding="utf-8")
        self.assertNotIn("처리 상태", modal)
        self.assertIn('class="d-none" id="event-status"', modal)
        self.assertIn('status = str(data.get("status") or "open")', event_views)
        self.assertIn('if creating and status == "draft"', event_views)
        self.assertIn('event.status = "void"', event_views)


class DepartmentSettingsContractTests(SimpleTestCase):
    def test_department_uses_hr_master_and_is_managed_from_my_company_info(self):
        myinfo_source = (ROOT / "views_myinfo.py").read_text(encoding="utf-8")
        settings_template = (ROOT / "templates" / "geoflow_ops" / "settings" / "settings_page.html").read_text(encoding="utf-8")
        myinfo_template = (ROOT / "templates" / "geoflow_ops" / "myinfo" / "orgunit_detail.html").read_text(encoding="utf-8")
        urls = (ROOT / "urls.py").read_text(encoding="utf-8")
        self.assertIn("FROM hr.departments", myinfo_source)
        self.assertIn("INSERT INTO hr.departments", myinfo_source)
        self.assertIn("UPDATE hr.departments", myinfo_source)
        self.assertIn("myinfo_department_save", myinfo_template)
        self.assertNotIn("settings_department_save", settings_template)
        self.assertIn("settings_department_save", urls)

    def test_migration_seeds_only_missing_initial_departments(self):
        migration = (ROOT / "migrations" / "0024_phase4_workflow_handoff_and_contract_access.py").read_text(encoding="utf-8")
        self.assertIn("('관리부'), ('GIS사업부'), ('지적사업부')", migration)
        self.assertIn("WHERE NOT EXISTS", migration)
        self.assertNotIn("DELETE FROM hr.departments", migration.upper())
        self.assertNotIn("TRUNCATE hr.departments", migration.upper())

    def test_migration_canonicalizes_legacy_departments_without_dropping_constraints(self):
        migration = (ROOT / "migrations" / "0024_phase4_workflow_handoff_and_contract_access.py").read_text(encoding="utf-8")
        self.assertIn("ADD COLUMN IF NOT EXISTS active boolean NOT NULL DEFAULT true", migration)
        self.assertIn("column_name = 'code'", migration)
        self.assertIn("INSERT INTO hr.departments (org_unit_id, code, name, active)", migration)
        self.assertIn("'phase4-' || md5", migration)
        self.assertIn("INSERT INTO hr.departments (org_unit_id, name, active)", migration)
        self.assertNotIn("DROP CONSTRAINT", migration.upper())
        self.assertNotIn("DROP INDEX", migration.upper())

    def test_department_create_preserves_legacy_code_constraint(self):
        source = (ROOT / "views_myinfo.py").read_text(encoding="utf-8")
        self.assertIn('"departments", "code"', source)
        self.assertIn('f"dept-{uuid4().hex}"', source)
        self.assertIn("INSERT INTO hr.departments (org_unit_id, code, name, active)", source)
        self.assertIn("INSERT INTO hr.departments (org_unit_id, name, active)", source)


class ContractDocumentAccessContractTests(SimpleTestCase):
    def test_contract_attachments_require_document_access_policy(self):
        source = (ROOT / "services" / "entity_access.py").read_text(encoding="utf-8")
        policy = (ROOT / "services" / "contract_access.py").read_text(encoding="utf-8")
        self.assertIn('attachment.entity_type == "contract"', source)
        self.assertIn("can_read_contract_documents", source)
        self.assertIn("PROJECT_ROLES", policy)
        self.assertIn("fail closed", policy.lower())

    def test_contract_document_access_is_request_and_management_approval(self):
        source = (ROOT / "views_contract_access.py").read_text(encoding="utf-8")
        template = (ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_detail.html").read_text(encoding="utf-8")
        self.assertIn("'pending'", source)
        self.assertIn('{"approved", "rejected"}', source)
        self.assertIn("계약 문서 열람 요청", template)
        self.assertIn("승인 대기", template)

    def test_access_request_migration_does_not_create_requests(self):
        migration = (ROOT / "migrations" / "0024_phase4_workflow_handoff_and_contract_access.py").read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS ops.contract_document_access_requests", migration)
        self.assertNotIn("INSERT INTO ops.contract_document_access_requests", migration)
