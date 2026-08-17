from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


def source(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


class Phase4ProjectParticipationScopeTests(unittest.TestCase):
    def test_migration_is_additive_and_preserves_existing_business_rows(self):
        migration = source("geoflow_ops/migrations/0022_phase4_project_participation_scope.py")
        lowered = migration.lower()
        self.assertIn('("webgisapp", "0021_phase4_employee_settings_foundation")', migration)
        self.assertIn("create table if not exists prj.project_members", lowered)
        self.assertIn("ux_project_members_one_active_pm", lowered)
        self.assertIn("ux_project_members_one_active_leader", lowered)
        self.assertIn("project_manager", migration)
        self.assertIn("project_leader", migration)
        self.assertIn("worker", migration)
        self.assertIn("viewer", migration)
        # The schema keeps the historical invited state for backward compatibility,
        # even though new project participation now requires an employee profile.
        self.assertIn("invited", migration)
        self.assertIn("active", migration)
        self.assertIn("revoked", migration)
        for destructive in (
            "delete from prj.projects",
            "truncate prj.projects",
            "drop table prj.projects",
            "delete from prj.scope_item",
            "truncate prj.scope_item",
            "delete from hr.employee_profile",
            "delete from ops.attachments",
        ):
            self.assertNotIn(destructive, lowered)

    def test_role_policy_matches_reviewed_project_boundaries(self):
        policy = source("geoflow_ops/services/project_access.py")
        for role in (
            "tenant_admin",
            "tenant_manager",
            "project_manager",
            "project_leader",
            "worker",
            "viewer",
        ):
            self.assertIn(role, policy)
        self.assertIn('mode = "full"', policy)
        self.assertIn('mode = "leader"', policy)
        self.assertIn('mode = "worker"', policy)
        self.assertIn('mode = "viewer"', policy)
        self.assertIn('return self.mode in {"full", "leader"}', policy)
        self.assertIn('if self.mode == "leader":', policy)
        self.assertIn('if self.mode == "viewer":', policy)
        self.assertIn('member["member_role"] in {"project_manager", "project_leader", "worker"}', policy)
        self.assertIn("active_memberships_for_request", policy)
        self.assertIn("_gf_project_memberships_cache", policy)
        self.assertIn("membership_status='active'", policy)

    def test_project_list_is_scoped_for_worker_and_viewer_modes(self):
        view = source("geoflow_ops/views_projects.py")
        self.assertIn("policy = project_access_policy(self.request, alias)", view)
        self.assertIn("visible_ids = policy.visible_project_ids()", view)
        self.assertIn("queryset = queryset.filter(pk__in=visible_ids)", view)
        self.assertIn("project_member_context(request, alias, obj.pk)", view)
        self.assertIn("requested_edit and policy.can_edit_project(obj.pk)", view)

    def test_project_scoped_entity_access_protects_events_and_attachments(self):
        entity = source("geoflow_ops/services/entity_access.py")
        self.assertIn('if scope_type == "project":', entity)
        self.assertIn("project_access_policy(request, alias).can_view(scope_id)", entity)
        self.assertIn("project_access_policy(request, alias).can_edit_project(scope_id)", entity)
        self.assertIn("has_scope_permission(request, scope_type, write=False)", entity)
        self.assertIn("Project writes are no longer a tenant-wide projects.edit decision", entity)
        self.assertIn("authorize_attachment_read", entity)
        self.assertIn("authorize_attachment_write", entity)
        self.assertIn("authorize_event_read", entity)
        self.assertIn("authorize_event_write", entity)

    def test_project_member_management_is_server_authorized(self):
        boundary = source("geoflow_ops/security_views.py")
        self.assertIn("def _require_project", boundary)
        self.assertIn('authorize_scope_read(request, alias, "project", pk)', boundary)
        self.assertIn('authorize_scope_write(request, alias, "project", pk)', boundary)
        for name in (
            "project_members_panel",
            "project_member_save",
            "project_member_revoke",
            "my_projects_api",
            "project_access_api",
        ):
            self.assertIn(f"def {name}", boundary)
        self.assertIn('def project_member_save(request, pk):\n    _require_project(request, pk, write=True)', boundary)
        self.assertIn('def project_member_revoke(request, pk, member_id):\n    _require_project(request, pk, write=True)', boundary)

        members = source("geoflow_ops/views_project_members.py")
        self.assertIn("policy.can_manage_members(project.pk)", members)
        self.assertIn("policy.assignable_member_roles(project.pk)", members)
        self.assertIn('member["can_revoke"]', members)
        self.assertIn("membership_status='revoked'", members)
        self.assertIn("Project Manager와 Project Leader는 프로젝트별 1명씩", members)
        self.assertIn('employee_id = _uuid(request.POST.get("employee_id"))', members)
        self.assertNotIn('request.POST.get("invite_email")', members)

    def test_webgis_scope_api_exposes_only_authorized_projects_and_write_flag(self):
        members = source("geoflow_ops/views_project_members.py")
        self.assertIn("def my_projects_api", members)
        self.assertIn("visible_ids = policy.visible_project_ids()", members)
        self.assertIn('"can_write": policy.can_webgis_write(project.pk)', members)
        self.assertIn("def project_access_api", members)
        self.assertIn("if not policy.can_webgis_read(project.pk)", members)

        urls = source("geoflow_ops/urls.py")
        self.assertIn('"api/projects/mine/"', urls)
        self.assertIn('"api/projects/<uuid:pk>/access/"', urls)

    def test_project_detail_uses_employee_profiles_for_all_participants(self):
        panel = source("geoflow_ops/templates/geoflow_ops/projects/_project_members_panel.html")
        for label in ("프로젝트 참여자", "PM 미지정", "Leader 미지정", "직원 참여 등록"):
            self.assertIn(label, panel)
        self.assertIn("WebGIS", panel)
        self.assertIn("계약직·일용직·파견·용역·프리랜서", panel)
        self.assertIn("{% if member.can_revoke %}", panel)
        self.assertNotIn('name="invite_email"', panel)

        members = source("geoflow_ops/views_project_members.py")
        self.assertIn("직원 페이지에 등록된 참여자를 선택하세요.", members)
        self.assertNotIn("VALUES (%s, %s, 'invited', %s, %s, true)", members)
        policy = source("geoflow_ops/services/project_access.py")
        self.assertIn("membership_status='active'", policy)

    def test_sensitive_new_routes_are_preflight_guarded(self):
        preflight = source("control/services/route_security_preflight.py")
        for path in (
            'f"/projects/{_UUID}/"',
            'f"/projects/{_UUID}/members/"',
            'f"/projects/{_UUID}/members/save/"',
            'f"/projects/{_UUID}/members/{_UUID2}/revoke/"',
            '"/api/projects/mine/"',
            'f"/api/projects/{_UUID}/access/"',
        ):
            self.assertIn(path, preflight)

    def test_iroomsng_legacy_webgis_is_not_modified_by_this_scope(self):
        migration = source("geoflow_ops/migrations/0022_phase4_project_participation_scope.py").lower()
        self.assertNotIn("iroomsng", migration)


if __name__ == "__main__":
    unittest.main()
