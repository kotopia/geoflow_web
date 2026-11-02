from contextlib import contextmanager, nullcontext
from inspect import unwrap
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import UUID

from django.http import HttpResponseRedirect
from django.test import RequestFactory, SimpleTestCase

from control import views_user_assignment as views
from control.services import tenant_employee_registration as registration


USER, GROUP, ROLE, ACTOR = (str(UUID(int=i)) for i in range(1, 5))


class EmployeeRegistrationTests(SimpleTestCase):
    def profile(self, rows, name="Employee"):
        cursor = MagicMock()
        cursor.fetchall.return_value = rows
        result = registration.register_employee_profile(
            cursor, user_id=USER, email="employee@example.invalid", name=name,
        )
        return result, cursor

    def test_new_profile_has_explicit_identity_and_no_role_copy(self):
        employee, cursor = self.profile([])
        sql, params = cursor.execute.call_args.args
        self.assertIn("INSERT INTO hr.employee_profile", sql)
        self.assertEqual(params, [employee, USER, "employee@example.invalid", "Employee"])
        self.assertNotIn("role_code", sql)

    def test_existing_employee_is_linked_without_overwriting_hr_fields(self):
        employee, cursor = self.profile([("employee", None, "EMPLOYEE@example.invalid", False)])
        self.assertEqual(employee, "employee")
        sql, params = cursor.execute.call_args.args
        self.assertIn("SET central_user_id", sql)
        for field in ("SET name", "role_code", "SET status", "department_id"):
            self.assertNotIn(field, sql)

    def test_repeat_registration_does_not_write_employee(self):
        employee, cursor = self.profile([("employee", USER, "employee@example.invalid", False)])
        self.assertEqual(employee, "employee")
        self.assertEqual(cursor.execute.call_count, 2)  # Lock + lookup only.

    def test_deleted_conflicting_ambiguous_and_mismatched_profiles_are_blocked(self):
        cases = [
            ([("employee", None, "employee@example.invalid", True)], "deleted"),
            ([("employee", ACTOR, "employee@example.invalid", False)], "linked_elsewhere"),
            ([("employee", USER, "other@example.invalid", False)], "email_mismatch"),
            ([("a", None, "employee@example.invalid", False)] * 2, "ambiguous"),
        ]
        for rows, expected in cases:
            with self.subTest(expected=expected), self.assertRaises(registration.RegistrationRejected) as raised:
                self.profile(rows)
            self.assertEqual(raised.exception.code, expected)

    def test_new_employee_requires_name_but_existing_employee_does_not(self):
        with self.assertRaises(registration.RegistrationRejected):
            self.profile([], name="")
        self.profile([("employee", USER, "employee@example.invalid", False)], name="")

    def run_registration(self, *, role_code="project_admin", eligible=True, fail=None):
        central = MagicMock()
        central.fetchone.side_effect = [(ACTOR,), ("employee@example.invalid", "Joined Name", role_code)]
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = central
        tenant = MagicMock()
        tenant.fetchall.return_value = []
        events = []

        @contextmanager
        def tenant_scope(group, *, write):
            self.assertEqual(group, GROUP)
            self.assertTrue(write)
            events.append("tenant_open")
            if fail == "tenant":
                raise RuntimeError("private-secret-value")
            yield tenant
            events.append("tenant_committed")

        def assign(user, group, role, *, before_assign):
            self.assertEqual((user, group, role), (USER, GROUP, ROLE))
            if not eligible:
                return False
            before_assign(central, (user, group, role))
            events.append("central_assign")
            if fail == "central":
                raise RuntimeError("private-secret-value")
            return True

        with patch.object(registration, "connections", {"default": connection}), patch.object(
            registration.transaction, "atomic", return_value=nullcontext(),
        ), patch.object(registration, "assign_group_role", side_effect=assign), patch.object(
            registration, "tenant_cursor", side_effect=tenant_scope,
        ):
            error = None
            try:
                registration.register_tenant_employee(user_id=USER, group_id=GROUP, role_id=ROLE, actor_user_id=ACTOR)
            except registration.RegistrationRejected as exc:
                error = exc
        return central, tenant, events, error

    def test_success_journals_attempt_then_commits_tenant_before_membership(self):
        central, tenant, events, error = self.run_registration()
        self.assertIsNone(error)
        self.assertEqual(events, ["tenant_open", "tenant_committed", "central_assign"])
        calls = central.execute.call_args_list
        self.assertIn("INSERT INTO tenant_employee_registrations", calls[1].args[0])
        self.assertIn("status='completed'", calls[-1].args[0])
        self.assertEqual(tenant.execute.call_args.args[1][-1], "Joined Name")

    def test_ineligible_account_cannot_open_tenant(self):
        central, tenant, events, error = self.run_registration(eligible=False)
        self.assertEqual(error.code, "ineligible")
        tenant.execute.assert_not_called()
        self.assertEqual(events, [])
        self.assertIn("status='failed'", central.execute.call_args.args[0])

    def test_central_role_cannot_open_tenant(self):
        _, tenant, events, error = self.run_registration(role_code="super_admin")
        self.assertEqual(error.code, "role_forbidden")
        tenant.execute.assert_not_called()

    def test_partial_and_total_failure_are_not_reported_as_success_or_leaked(self):
        for failure in ("tenant", "central"):
            with self.subTest(failure=failure):
                central, _, events, error = self.run_registration(fail=failure)
                self.assertEqual(error.code, "storage_error")
                self.assertNotIn("private-secret-value", str(error))
                self.assertIn("status='failed'", central.execute.call_args.args[0])
                self.assertEqual("tenant_committed" in events, failure == "central")

    def test_invalid_ids_never_open_any_database(self):
        with patch.object(registration, "connections") as connections:
            with self.assertRaises(ValueError):
                registration.register_tenant_employee(user_id=USER, group_id="default", role_id=ROLE, actor_user_id=ACTOR)
            connections.__getitem__.assert_not_called()


class EmployeeRegistrationRouteTests(SimpleTestCase):
    def test_unauthorized_request_is_denied_before_registration(self):
        request = RequestFactory().post("/", {})
        with patch("control.decorators.lookup_user_id_from_request", return_value=None), patch.object(
            registration, "register_tenant_employee",
        ) as register:
            self.assertEqual(views.users_register_employee_admin(request, UUID(USER)).status_code, 403)
            register.assert_not_called()

    def test_csrf_and_post_are_enforced(self):
        request = RequestFactory().post("/", {})
        # Bypass ONLY the tested central guard; keep the real CSRF/POST wrappers.
        guarded = views.users_register_employee_admin.__wrapped__
        self.assertEqual(guarded(request, UUID(USER)).status_code, 403)
        request = RequestFactory().get("/")
        self.assertEqual(guarded(request, UUID(USER)).status_code, 405)

    def test_view_reports_failure_without_success(self):
        request = RequestFactory().post("/", {"group_id": GROUP, "role_id": ROLE})
        with patch.object(views, "lookup_user_id_from_request", return_value=ACTOR), patch.object(
            registration, "register_tenant_employee", side_effect=registration.RegistrationRejected("deleted", "삭제된 직원입니다."),
        ), patch.object(views.messages, "success") as success, patch.object(views.messages, "error") as error, patch.object(
            views, "redirect", return_value=HttpResponseRedirect("/"),
        ):
            response = unwrap(views.users_register_employee_admin)(request, UUID(USER))
        self.assertEqual(response.status_code, 302)
        success.assert_not_called()
        error.assert_called_once()
