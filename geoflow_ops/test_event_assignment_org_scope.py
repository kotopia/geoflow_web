from inspect import getsource

from django.test import SimpleTestCase

from geoflow_ops import views_workboard


class EventAssignmentOrgScopeTests(SimpleTestCase):
    def test_contract_and_project_assignment_resolve_legal_company(self):
        source = getsource(views_workboard._scope_assignment_org_unit)
        self.assertIn('scope_type == "contract"', source)
        self.assertIn('Contract.objects.using(alias)', source)
        self.assertIn('"org_unit_id"', source)
        self.assertIn('scope_type == "project"', source)
        self.assertIn('"contract__org_unit_id"', source)

    def test_department_options_are_active_and_scoped_to_contract_company(self):
        source = getsource(views_workboard.assignment_options)
        self.assertIn('WHERE active=true', source)
        self.assertIn('(org_unit_id=%s OR org_unit_id IS NULL)', source)
        self.assertIn('assignment_scope = "contract_org"', source)
        self.assertIn('assignment_scope = "tenant_fallback"', source)

    def test_people_remain_tenant_wide_for_cross_company_collaboration(self):
        source = getsource(views_workboard.assignment_options)
        self.assertIn("People are intentionally tenant-wide", source)
        self.assertIn('"department_id": ""', source)
        self.assertIn('"home_department_id"', source)
        self.assertIn("status <> '퇴사'", source)
