from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class Phase4SettingsWorkflowFixesTests(unittest.TestCase):
    def test_project_scope_legacy_guards_use_exact_project_bridge(self):
        boundary = source("geoflow_ops/security_views.py")
        permissions = source("control/gf_authz/permissions.py")
        self.assertIn('request._gf_project_scope_authorized = {', boundary)
        self.assertIn('"project_id": str(pk)', boundary)
        self.assertIn('"write": bool(write)', boundary)
        self.assertIn("def _project_scope_override", permissions)
        self.assertIn('str(project_id) != str(scope.get("project_id") or "")', permissions)
        self.assertIn('if "projects.edit" in codes:', permissions)
        for handler in (
            "project_summary", "project_summary_save", "project_scope_modal",
            "project_scope_data", "project_scope_save", "project_member_save",
            "project_member_revoke",
        ):
            self.assertIn(f"def {handler}", boundary)
        self.assertIn("_require_project(request, pk, write=True)", boundary)

    def test_legacy_completed_contracts_are_converted_not_runtime_compatible(self):
        forms = source("geoflow_ops/forms.py")
        settings_view = source("geoflow_ops/views_settings.py")
        detail = source("geoflow_ops/templates/geoflow_ops/contracts/contract_detail.html")
        workflow = source("geoflow_ops/services/workflow_state.py")
        migration = source("geoflow_ops/migrations/0026_contract_completion_event_backfill.py")

        self.assertIn('"contract.status"', settings_view)
        self.assertIn("HIDDEN_SETTINGS_SYSTEM_KEYS", settings_view)
        self.assertNotIn('settings_options(alias, "contract.status")', forms)
        self.assertNotIn('name="status"', detail)
        self.assertNotIn("운영상태", detail)

        runtime_body = workflow.split("def contract_workflow_summaries", 1)[1]
        self.assertNotIn('getattr(contract, "status"', runtime_body)
        self.assertNotIn("SELECT status FROM ctr.contracts", workflow)
        self.assertNotIn("UPDATE ctr.contracts", workflow)
        self.assertIn("event-derived", workflow)
        self.assertIn("legacy_contract_status_migration", migration)
        self.assertIn("SET status = NULL", migration)
        self.assertIn("'closeout_complete'", migration)

    def test_contract_kind_and_event_vocabularies_remain_tenant_settings_driven(self):
        forms = source("geoflow_ops/forms.py")
        service = source("geoflow_ops/services/tenant_settings.py")
        migration = source("geoflow_ops/migrations/0023_phase4_configurable_workflow_foundation.py")
        detail = source("geoflow_ops/templates/geoflow_ops/contracts/contract_detail.html")
        self.assertIn('settings_options(alias, "contract.kind")', forms)
        self.assertIn("for value, label in form.kind.field.choices", detail)
        self.assertIn("process-workboard-ui.js", detail)
        self.assertIn("data-workflow-options-url", detail)
        for key in (
            "contract.status", "contract.kind", "event.stage", "event.type", "event.status",
            "event.type.pre_contract", "event.type.contract", "event.type.kickoff",
            "event.type.execution", "event.type.inspection", "event.type.closeout",
            "event.type.billing",
        ):
            self.assertIn(key, migration)
        self.assertIn("def event_workflow_options", service)
        self.assertIn("def event_type_allowed", service)
        self.assertIn("category.code = %s", service)
        self.assertIn("category.system_key IS NULL", service)
        self.assertIn("SYSTEM_REQUIRED_OPTIONS", service)
        self.assertIn('"event.stage": tuple((choice.code, choice.label) for choice in STAGE_CHOICES)', service)
        self.assertIn('SYSTEM_REQUIRED_OPTIONS[f"event.type.{_stage.code}"]', service)
        self.assertIn("DEPRECATED_EVENT_TYPE_CODES", service)

    def test_required_event_stages_are_immutable_in_ui_and_server(self):
        template = source("geoflow_ops/templates/geoflow_ops/settings/settings_page.html")
        view = source("geoflow_ops/views_settings.py")
        self.assertIn("필수·고정", template)
        self.assertIn("node.immutable", template)
        self.assertIn("settings-save-button", template)
        self.assertIn("def _is_immutable_event_stage", view)
        self.assertIn('key == "event.stage" or key.startswith("event.stage.")', view)
        self.assertIn("필수 업무단계는 시스템 기준값으로 수정할 수 없습니다.", view)

    def test_environment_settings_shows_six_stage_standard_and_hides_retired_system_rows(self):
        template = source("geoflow_ops/templates/geoflow_ops/settings/settings_page.html")
        view = source("geoflow_ops/views_settings.py")
        process = source("geoflow_ops/process_workflow.py")

        self.assertIn('id="workflow-standard-settings"', template)
        self.assertIn("업무 프로세스 기준", template)
        self.assertIn("workflow_settings", view)
        self.assertIn("def _workflow_settings_summary", view)
        for token in (
            'WorkflowChoice("preparation", "준비")',
            'WorkflowChoice("contract", "계약")',
            'WorkflowChoice("kickoff", "착수")',
            'WorkflowChoice("execution", "수행")',
            'WorkflowChoice("closeout", "준공")',
            'WorkflowChoice("complete", "완료")',
        ):
            self.assertIn(token, process)
        for retired_key in (
            '"event.stage.pre_contract"',
            '"event.stage.inspection"',
            '"event.stage.billing"',
            '"event.type.pre_contract"',
            '"event.type.inspection"',
            '"event.type.billing"',
        ):
            self.assertIn(retired_key, view)
        self.assertIn("DEPRECATED_EVENT_TYPE_CODES", view)
        self.assertIn("canonical_stage != parent_stage", view)
        self.assertIn("이력 호환을 위해 데이터베이스에 보존", template)

    def test_canonical_transition_events_are_available_in_generic_event_dropdown(self):
        process = source("geoflow_ops/process_workflow.py")
        service = source("geoflow_ops/services/tenant_settings.py")
        self.assertIn('WorkflowChoice("closeout_approved", "준공승인")', process)
        self.assertIn("Canonical transition", service)
        self.assertNotIn("code != CONTRACT_COMPLETION_EVENT_TYPE", service)
        self.assertIn("code not in DEPRECATED_EVENT_TYPE_CODES", service)

    def test_event_type_is_filtered_by_stage_and_canonicalized_server_side(self):
        event_guard = source("geoflow_ops/event_security_views.py")
        js = source("geoflow_ops/static/geoflow_ops/js/process-workboard-ui.js")
        urls = source("geoflow_ops/urls.py")
        self.assertIn("def workflow_options", event_guard)
        self.assertIn("event_type_allowed(alias, stage, event_type)", event_guard)
        self.assertIn("event_type_allowed(alias, incoming_stage, incoming_type)", event_guard)
        self.assertIn("_canonicalize_workflow_write", event_guard)
        self.assertIn("normalize_event_type_for_write", event_guard)
        self.assertIn("stage_changed = incoming_stage != existing_stage", event_guard)
        self.assertIn("type_changed = incoming_type != existing_type", event_guard)
        self.assertIn("function populateEventTypes", js)
        self.assertIn("fStage.onchange", js)
        self.assertIn("types_by_stage", js)
        self.assertIn('"api/events/workflow-options/"', urls)

    def test_workboard_write_flags_use_exact_scope_authorization(self):
        workboard = source("geoflow_ops/views_workboard.py")
        self.assertIn("authorize_scope_write(request, alias, event.scope_type, event.scope_id)", workboard)
        self.assertIn("scope_can_write = bool(authorize_scope_write(request, alias, scope_type, scope_id))", workboard)
        self.assertNotIn('item["can_write"] = bool(has_scope_permission(request, event.scope_type, write=True))', workboard)

    def test_settings_tree_has_expand_and_collapse_controls(self):
        template = source("geoflow_ops/templates/geoflow_ops/settings/settings_page.html")
        for token in ("btn-tree-expand", "btn-tree-collapse", "data-tree-toggle", "collapsed", "refreshTreeVisibility"):
            self.assertIn(token, template)

    def test_external_project_people_are_employee_profiles_not_new_email_invites(self):
        view = source("geoflow_ops/views_project_members.py")
        template = source("geoflow_ops/templates/geoflow_ops/projects/_project_members_panel.html")
        migration = source("geoflow_ops/migrations/0023_phase4_configurable_workflow_foundation.py")
        self.assertIn('employee_id = _uuid(request.POST.get("employee_id"))', view)
        self.assertIn("직원 페이지에 등록된 참여자를 선택하세요.", view)
        self.assertNotIn('request.POST.get("invite_email")', view)
        self.assertNotIn('name="invite_email"', template)
        self.assertIn("계약직·일용직·파견·용역·프리랜서", template)
        self.assertIn("'일용직', '일용직'", migration)

    def test_contract_list_keeps_shared_four_filter_groups_over_six_stage_workflow(self):
        base = source("geoflow_ops/templates/geoflow_ops/base_tenant.html")
        list_template = source("geoflow_ops/templates/geoflow_ops/contracts/contract_list.html")
        js = source("geoflow_ops/static/geoflow_ops/js/gf-list-core.js")
        workflow = source("geoflow_ops/services/workflow_state.py")
        self.assertIn("GEOFLOW_TENANT_VOCABULARY", base)
        self.assertIn("data-kind-code", list_template)
        self.assertIn("contractKind", list_template)
        self.assertNotIn("운영상태", list_template)
        for token in ("planned: '계약'", "active: '진행'", "pause: '준공'", "complete: '완료'"):
            self.assertIn(token, list_template)
        self.assertIn('"preparation": "planned"', workflow)
        self.assertIn('"kickoff": "active"', workflow)
        self.assertIn("function canonicalStatus", js)
        self.assertIn('completed:"complete"', js)

    def test_new_workflow_route_is_preflight_guarded(self):
        preflight = source("control/services/route_security_preflight.py")
        self.assertIn(
            '("/api/events/workflow-options/", "tenant:event_workflow_options", "geoflow_ops.event_security_views", "workflow_options")',
            preflight,
        )


if __name__ == "__main__":
    unittest.main()
