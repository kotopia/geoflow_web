from inspect import getsource

from django.test import SimpleTestCase

from geoflow_ops import views_events, views_workboard
from geoflow_ops.services import department_routing


class EventAssignmentOrgScopeTests(SimpleTestCase):
    def test_contract_and_project_assignment_resolve_legal_company(self):
        source = getsource(department_routing.scope_org_unit_id)
        self.assertIn('scope_type == "contract"', source)
        self.assertIn("ctr.contracts", source)
        self.assertIn('scope_type == "project"', source)
        self.assertIn("COALESCE(c.org_unit_id, p.org_unit_id)", source)
        self.assertIn("LEFT JOIN ctr.contracts", source)

    def test_department_options_are_active_and_scoped_to_contract_company(self):
        source = getsource(views_workboard.assignment_options)
        self.assertIn("scope_org_unit_id(alias, scope_type, scope_id)", source)
        self.assertIn("WHERE active=true", source)
        self.assertIn("(org_unit_id=%s::uuid OR org_unit_id IS NULL)", source)
        self.assertIn('assignment_scope = "contract_org"', source)
        self.assertIn('assignment_scope = "tenant_fallback"', source)

    def test_people_remain_tenant_wide_for_cross_company_collaboration(self):
        source = getsource(views_workboard.assignment_options)
        self.assertIn("People are intentionally tenant-wide", source)
        self.assertIn('"department_id": ""', source)
        self.assertIn('"home_department_id"', source)
        self.assertIn('"org_unit_id"', source)
        self.assertIn("status <> '퇴사'", source)

    def test_department_write_guard_matches_assignment_scope(self):
        source = getsource(department_routing.department_allowed_for_scope)
        self.assertIn("scope_org_unit_id", source)
        self.assertIn("active=true", source)
        self.assertIn("org_unit_id=%s::uuid OR org_unit_id IS NULL", source)

        create_source = getsource(views_events.create_event)
        self.assertIn("department_allowed_for_scope", create_source)
        self.assertIn('return _json_error("Invalid owner_department_id")', create_source)

        update_source = getsource(views_events.update_event)
        self.assertIn("department_allowed_for_scope", update_source)
        self.assertIn("incoming_department_id != event.owner_department_id", update_source)
        self.assertIn('return _json_error("Invalid owner_department_id")', update_source)
