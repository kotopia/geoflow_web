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

    def test_contract_status_is_canonical_complete_and_dashboard_hides_terminal_contracts(self):
        forms = source("geoflow_ops/forms.py")
        settings = source("geoflow_ops/services/tenant_settings.py")
        dashboard = source("geoflow_ops/views_dashboard.py")
        migration = source("geoflow_ops/migrations/0023_phase4_configurable_workflow_foundation.py")
        detail = source("geoflow_ops/templates/geoflow_ops/contracts/contract_detail.html")
        self.assertIn('(\"complete\", \"완료\")', settings)
        self.assertNotIn('(\"completed\", \"완료\")', forms)
        self.assertIn('status == "complete"', forms)
        self.assertIn('qs = qs.exclude(status__in=terminal).exclude(contract__status__in=terminal)', dashboard)
        self.assertIn("WHEN 'completed' THEN 'complete'", migration)
        self.assertIn("WHEN '완료' THEN 'complete'", migration)
        self.assertNotIn('option value="completed"', detail)
        self.assertIn("for value, label in form.status.field.choices", detail)
        for destructive in ("delete from ctr.contracts", "truncate ctr.contracts", "drop table ctr.contracts"):
            self.assertNotIn(destructive, migration.lower())

    def test_contract_and_event_vocabularies_are_tenant_settings_driven(self):
        forms = source("geoflow_ops/forms.py")
        service = source("geoflow_ops/services/tenant_settings.py")
        migration = source("geoflow_ops/migrations/0023_phase4_configurable_workflow_foundation.py")
        detail = source("geoflow_ops/templates/geoflow_ops/contracts/contract_detail.html")
        self.assertIn('settings_options(alias, "contract.status")', forms)
        self.assertIn('settings_options(alias, "contract.kind")', forms)
        self.assertIn("for value, label in form.status.field.choices", detail)
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

    def test_event_type_is_filtered_by_stage_in_ui_and_rejected_server_side(self):
        event_guard = source("geoflow_ops/event_security_views.py")
        js = source("geoflow_ops/static/geoflow_ops/js/process-workboard-ui.js")
        urls = source("geoflow_ops/urls.py")
        self.assertIn("def workflow_options", event_guard)
        self.assertIn("event_type_allowed(alias, stage, event_type)", event_guard)
        self.assertIn("event_type_allowed(alias, incoming_stage, incoming_type)", event_guard)
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
        view = source("geoflow_ops/views_settings.py")
        for token in ("btn-tree-expand", "btn-tree-collapse", "data-tree-toggle", "collapsed", "refreshTreeVisibility"):
            self.assertIn(token, template)
        self.assertIn('if node_type != "value":', view)
        self.assertIn("active = True", view)

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

    def test_shared_contract_list_uses_tenant_labels_and_alias_canonicalization(self):
        base = source("geoflow_ops/templates/geoflow_ops/base_tenant.html")
        list_template = source("geoflow_ops/templates/geoflow_ops/contracts/contract_list.html")
        js = source("geoflow_ops/static/geoflow_ops/js/gf-list-core.js")
        self.assertIn("GEOFLOW_TENANT_VOCABULARY", base)
        self.assertIn("data-kind-code", list_template)
        self.assertIn("contractKind", list_template)
        self.assertIn("function canonicalStatus", js)
        self.assertIn('completed:"complete"', js)
        self.assertIn("contractLabels", js)

    def test_new_workflow_route_is_preflight_guarded(self):
        preflight = source("control/services/route_security_preflight.py")
        self.assertIn(
            '("/api/events/workflow-options/", "tenant:event_workflow_options", "geoflow_ops.event_security_views", "workflow_options")',
            preflight,
        )


if __name__ == "__main__":
    unittest.main()
