from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase

from geoflow_ops.services.event_handoff import (
    default_event_status,
    event_type_allowed_for_scope,
)
from geoflow_ops.services.workflow_state import _major_phase_for_event


ROOT = Path(__file__).resolve().parent


class EventHandoffVocabularyTests(SimpleTestCase):
    def test_request_events_stay_open_and_records_complete_automatically(self):
        self.assertEqual(default_event_status("inspection_request"), "open")
        self.assertEqual(default_event_status("correction_request"), "open")
        self.assertEqual(default_event_status("reinspection"), "open")
        self.assertEqual(default_event_status("contract_doc"), "done")
        self.assertEqual(default_event_status("progress_report"), "done")

    def test_contract_and_project_use_one_engine_but_keep_scope_vocabulary(self):
        self.assertTrue(event_type_allowed_for_scope("contract", "contract_doc"))
        self.assertFalse(event_type_allowed_for_scope("project", "contract_doc"))
        self.assertTrue(event_type_allowed_for_scope("project", "inspection_request"))
        self.assertFalse(event_type_allowed_for_scope("contract", "inspection_request"))
        self.assertTrue(event_type_allowed_for_scope("project", "etc"))
        self.assertTrue(event_type_allowed_for_scope("contract", "etc"))

    def test_actual_kickoff_starts_execution_but_kickoff_document_does_not(self):
        self.assertEqual(
            _major_phase_for_event(SimpleNamespace(stage="kickoff", event_type="kickoff")),
            "execution",
        )
        self.assertEqual(
            _major_phase_for_event(SimpleNamespace(stage="kickoff", event_type="kickoff_doc")),
            "contract",
        )
        self.assertEqual(
            _major_phase_for_event(SimpleNamespace(stage="inspection", event_type="inspection_request")),
            "closeout",
        )
        self.assertIsNone(
            _major_phase_for_event(SimpleNamespace(stage="billing", event_type="advance_payment"))
        )


class EventHandoffMigrationContractTests(SimpleTestCase):
    def test_0024_is_additive_and_preserves_existing_business_rows(self):
        source = (ROOT / "migrations" / "0024_phase4_event_handoff_and_contract_access.py").read_text(encoding="utf-8")
        lowered = source.lower()
        self.assertIn('("webgisapp", "0023_phase4_configurable_workflow_foundation")', source)
        self.assertIn("관리부", source)
        self.assertIn("GIS사업부", source)
        self.assertIn("지적사업부", source)
        self.assertIn("CREATE TABLE IF NOT EXISTS ops.contract_document_access_requests", source)
        self.assertIn("WHERE status='pending'", source)
        for token in (
            "delete from ctr.contracts",
            "truncate ctr.contracts",
            "drop table ctr.contracts",
            "delete from prj.projects",
            "truncate prj.projects",
            "delete from ops.process_events",
            "truncate ops.process_events",
            "delete from hr.employee_profile",
            "delete from ops.attachments",
        ):
            self.assertNotIn(token, lowered)

    def test_contract_document_access_is_tenant_local_and_time_limited(self):
        service = (ROOT / "services" / "contract_document_access.py").read_text(encoding="utf-8")
        self.assertIn("ops.contract_document_access_requests", service)
        self.assertIn("project_access_policy(request, alias).can_view", service)
        self.assertIn("timedelta(days=7)", service)
        self.assertIn('gf_has_perm(request, "contracts.edit")', service)
        self.assertNotIn("control.models", service)


class EventHandoffImplementationContractTests(SimpleTestCase):
    def test_contract_workflow_keeps_operational_status_separate(self):
        workflow = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")
        contract_list = (ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_list.html").read_text(encoding="utf-8")
        contract_detail = (ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_detail.html").read_text(encoding="utf-8")
        self.assertIn('("contract", "계약(전)")', workflow)
        self.assertIn('("execution", "수행(진행)")', workflow)
        self.assertIn('("closeout", "준공")', workflow)
        self.assertNotIn('"billing": "closeout"', workflow)
        self.assertIn("업무흐름", contract_list)
        self.assertIn("운영상태", contract_list)
        self.assertIn("현재 업무흐름", contract_detail)
        self.assertIn("계약(전)", contract_detail)
        self.assertIn("수행(진행)", contract_detail)
        self.assertIn("준공", contract_detail)

    def test_event_status_is_hidden_from_manual_choice_and_has_explicit_complete_action(self):
        modal = (ROOT / "templates" / "geoflow_ops" / "events" / "_event_modal.html").read_text(encoding="utf-8")
        js = (ROOT / "static" / "geoflow_ops" / "js" / "event-status-auto-ui.js").read_text(encoding="utf-8")
        views = (ROOT / "views_events.py").read_text(encoding="utf-8")
        self.assertIn('class="d-none" id="event-status"', modal)
        self.assertIn('id="btn-complete-event-modal"', modal)
        self.assertIn("default_event_status(event_type)", views)
        self.assertIn("status.value = 'done'", js)

    def test_department_settings_use_hr_department_master_and_active_assignment_options(self):
        settings_view = (ROOT / "views_settings.py").read_text(encoding="utf-8")
        settings_template = (ROOT / "templates" / "geoflow_ops" / "settings" / "settings_page.html").read_text(encoding="utf-8")
        workboard = (ROOT / "views_workboard.py").read_text(encoding="utf-8")
        self.assertIn("hr.departments", settings_view)
        self.assertIn("담당부서", settings_template)
        self.assertIn("settings_department_save", settings_template)
        self.assertIn("FROM hr.departments\n             WHERE active=true", workboard)

    def test_handoff_rules_return_inspection_to_management_and_correction_to_business(self):
        source = (ROOT / "services" / "event_handoff.py").read_text(encoding="utf-8")
        self.assertIn('MANAGEMENT_DEPARTMENT_NAME = "관리부"', source)
        self.assertIn('if event_type == "correction_request"', source)
        self.assertIn('if event_type in {"inspection_request", "inspection", "reinspection"}', source)
        self.assertIn("AND project_id=%s::uuid", source)
        self.assertIn("event_type = ANY(%s::text[])", source)

    def test_requested_contract_document_access_does_not_expand_contract_surface(self):
        entity_access = (ROOT / "services" / "entity_access.py").read_text(encoding="utf-8")
        project_template = (ROOT / "templates" / "geoflow_ops" / "projects" / "project_detail.html").read_text(encoding="utf-8")
        access_views = (ROOT / "contract_access_views.py").read_text(encoding="utf-8")
        self.assertIn('if attachment.entity_type == "contract"', entity_access)
        self.assertIn("contract_document_access", entity_access)
        self.assertIn("project_contract_document_panel", project_template)
        self.assertIn('authorize_scope_read(request, alias, "project", pk)', access_views)
        self.assertNotIn("authorize_scope_read(request, alias, \"contract\", project.contract_id)", access_views)

    def test_scope_filtered_workflow_options_are_used_by_contract_and_project_pages(self):
        security = (ROOT / "event_security_views.py").read_text(encoding="utf-8")
        contract_template = (ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_detail.html").read_text(encoding="utf-8")
        project_template = (ROOT / "templates" / "geoflow_ops" / "projects" / "project_detail.html").read_text(encoding="utf-8")
        self.assertIn("event_type_allowed_for_scope", security)
        self.assertIn("?scope_type=contract", contract_template)
        self.assertIn("?scope_type=project", project_template)
