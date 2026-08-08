from inspect import getsource

from django.test import SimpleTestCase

from geoflow_ops import employee_security_views


class EmployeeSecurityBoundaryTests(SimpleTestCase):
    def test_read_employee_boundaries_are_get_only(self):
        for view in (
            employee_security_views.employee_list,
            employee_security_views.hr_options,
        ):
            with self.subTest(view=view.__name__):
                source = getsource(view)
                self.assertIn("@login_required", source)
                self.assertIn("@require_GET", source)

    def test_sensitive_employee_pages_are_never_cached(self):
        for view in (
            employee_security_views.employee_list,
            employee_security_views.employee_create,
            employee_security_views.employee_detail,
            employee_security_views.employee_role_request,
        ):
            with self.subTest(view=view.__name__):
                self.assertIn("@never_cache", getsource(view))

    def test_employee_create_detail_and_role_request_allow_only_get_post(self):
        for view in (
            employee_security_views.employee_create,
            employee_security_views.employee_detail,
            employee_security_views.employee_role_request,
        ):
            with self.subTest(view=view.__name__):
                source = getsource(view)
                self.assertIn("@login_required", source)
                self.assertIn('@require_http_methods(["GET", "POST"])', source)

    def test_employee_detail_write_requires_directory_edit(self):
        source = getsource(employee_security_views.employee_detail)
        self.assertIn('gf_has_perm(request, "directory.edit")', source)

    def test_role_request_uses_role_assignment_permission(self):
        source = getsource(employee_security_views.employee_role_request)
        self.assertIn('"directory.roles.assign"', source)
