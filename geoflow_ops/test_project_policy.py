from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import patch
from django.core.exceptions import PermissionDenied,ValidationError
from django.test import RequestFactory
from django.template.loader import get_template
from . import security_views
from .models import Project,Contract
from .forms import ProjectForm
from .services.contract_project_pair import project_mode,normalized_name

class ProjectPolicyTests(TestCase):
    def test_invalid_or_missing_mode_fails_closed(self):
        for ext in ({},{'project_mode':'invalid'},[],{'project_mode':None}):
            with self.assertRaises(ValidationError):project_mode(Contract(ext=ext))
    def test_name_warning_normalization(self):
        self.assertEqual(normalized_name(' Ａ  B '),normalized_name('a b'))
    def test_creation_requires_all_permissions_before_view(self):
        for missing in ('projects.view','projects.edit','contracts.view'):
            request=RequestFactory().post('/projects/new/',{'contract':'other-tenant'})
            request.user=SimpleNamespace(is_authenticated=True)
            with patch.object(security_views,'require_tenant_context',return_value='tenant'),patch.object(security_views,'gf_has_perm',side_effect=lambda r,p:p!=missing),patch.object(security_views.views_projects,'project_create') as view:
                with self.assertRaises(PermissionDenied):security_views.project_create(request)
                view.assert_not_called()
    def test_project_leader_cannot_create_new_global_project(self):
        request=RequestFactory().post('/projects/new/');request.user=SimpleNamespace(is_authenticated=True)
        with patch.object(security_views,'require_tenant_context',return_value='tenant'),patch.object(security_views,'gf_has_perm',return_value=True),patch('geoflow_ops.services.project_access.project_access_policy',return_value=SimpleNamespace(can_edit_all=False)),patch.object(security_views.views_projects,'project_create') as view:
            with self.assertRaises(PermissionDenied):security_views.project_create(request)
            view.assert_not_called()
    def test_cross_tenant_context_rejected_before_query(self):
        from .services.entity_access import require_tenant_context
        request=SimpleNamespace(session={'tenant_db_alias':'other'})
        with patch('geoflow_ops.services.entity_access.current_db_alias',return_value='tenant'):
            with self.assertRaises(PermissionDenied):require_tenant_context(request)
    @patch('geoflow_ops.services.project_status.project_status_options',return_value=[('active','진행')])
    def test_single_name_disabled_multiple_name_editable(self,_):
        for mode in ('SINGLE','MULTIPLE'):
            contract=Contract(name='Authoritative',ext={'project_mode':mode})
            project=Project(contract=contract,name='Old');project._state.adding=False
            form=ProjectForm(instance=project,alias='default')
            self.assertEqual(form.fields['name'].disabled,mode=='SINGLE')
            self.assertTrue(form.fields['contract'].disabled)
            self.assertNotIn('code',form.fields)
    def test_changed_templates_compile(self):
        for path in ('projects/project_list.html','projects/project_detail.html','projects/project_form.html','contracts/contract_detail.html'):
            get_template('geoflow_ops/'+path)
