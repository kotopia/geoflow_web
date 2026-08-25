from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch

from geoflow_ops.services.project_access import ProjectAccessPolicy, project_access_policy


class TenantProjectRolePolicyTests(TestCase):
    def _request(self, role):
        return SimpleNamespace(
            session={"gf_roles": [role]},
            user=SimpleNamespace(is_authenticated=True, email="person@example.test"),
        )

    @patch("geoflow_ops.services.project_access._current_employee_id", return_value="employee-id")
    def test_project_admin_has_all_project_read_and_write(self, _employee):
        policy = project_access_policy(self._request("project_admin"), "tenant")
        self.assertEqual(policy.mode, "full")
        self.assertTrue(policy.can_view("00000000-0000-0000-0000-000000000001"))
        self.assertTrue(policy.can_webgis_write("00000000-0000-0000-0000-000000000001"))
        self.assertIsNone(policy.visible_project_ids())

    @patch("geoflow_ops.services.project_access._current_employee_id", return_value="employee-id")
    def test_project_coordinator_views_all_but_operates_only_memberships(self, _employee):
        policy = project_access_policy(self._request("project_coordinator"), "tenant")
        self.assertEqual(policy.mode, "leader")
        self.assertTrue(policy.can_view("00000000-0000-0000-0000-000000000001"))
        with patch.object(ProjectAccessPolicy, "membership", return_value=None):
            self.assertFalse(policy.can_edit_project("00000000-0000-0000-0000-000000000001"))
            self.assertFalse(policy.can_webgis_write("00000000-0000-0000-0000-000000000001"))
        with patch.object(ProjectAccessPolicy, "membership", return_value={"member_role": "viewer"}):
            self.assertTrue(policy.can_edit_project("00000000-0000-0000-0000-000000000001"))
            self.assertTrue(policy.can_webgis_write("00000000-0000-0000-0000-000000000001"))

    def test_worker_and_viewer_remain_membership_scoped(self):
        for mode in ("worker", "viewer"):
            policy = ProjectAccessPolicy("tenant", object(), mode, "employee-id")
            with patch.object(ProjectAccessPolicy, "membership", return_value=None):
                self.assertFalse(policy.can_view("00000000-0000-0000-0000-000000000001"))
                self.assertFalse(policy.can_webgis_write("00000000-0000-0000-0000-000000000001"))

        worker = ProjectAccessPolicy("tenant", object(), "worker", "employee-id")
        viewer = ProjectAccessPolicy("tenant", object(), "viewer", "employee-id")
        membership = {"member_role": "worker"}
        with patch.object(ProjectAccessPolicy, "membership", return_value=membership):
            self.assertTrue(worker.can_webgis_read("00000000-0000-0000-0000-000000000001"))
            self.assertTrue(worker.can_webgis_write("00000000-0000-0000-0000-000000000001"))
            self.assertTrue(viewer.can_webgis_read("00000000-0000-0000-0000-000000000001"))
            self.assertFalse(viewer.can_webgis_write("00000000-0000-0000-0000-000000000001"))
