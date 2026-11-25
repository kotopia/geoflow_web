from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from django.core.exceptions import PermissionDenied,ValidationError
from django.test import RequestFactory, override_settings
from django.template.loader import get_template
from . import security_views
from .models import Project,Contract
from .forms import ProjectForm, ContractForm
from django.forms import TextInput
from .services.contract_project_pair import project_mode,normalized_name

class ProjectPolicyTests(TestCase):
    def test_manager_lookup_preserves_tenant_and_requested_project_scope(self):
        from .views_project_members import project_manager_names
        with patch('geoflow_ops.views_project_members.connections') as connections:
            self.assertEqual(project_manager_names('tenant_fixture', []), {})
            connections.__getitem__.assert_not_called()
            cursor = connections.__getitem__.return_value.cursor.return_value.__enter__.return_value
            cursor.fetchone.return_value = (False,)
            self.assertEqual(project_manager_names('tenant_fixture', ['project-fixture']), {})
            self.assertEqual(cursor.execute.call_count, 1)
            cursor.reset_mock()
            cursor.fetchone.return_value = (True,)
            cursor.fetchall.return_value = [('project-fixture', '담당자'), ('project-fixture', ''), ('project-fixture', '초대 담당자')]
            self.assertEqual(project_manager_names('tenant_fixture', ['project-fixture']), {'project-fixture': '담당자, 초대 담당자'})
            sql, params = cursor.execute.call_args.args
            self.assertEqual(params, [['project-fixture']])
            self.assertIn('m.project_id=ANY(%s::uuid[])', sql)
            self.assertIn("m.membership_status='active'", sql)
            self.assertIn("m.member_role='project_manager'", sql)
            self.assertIn('e.is_deleted=false', sql)
            self.assertTrue(all(call.args == ('tenant_fixture',) for call in connections.__getitem__.call_args_list))

    @override_settings(TEMPLATES=[{
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'APP_DIRS': True,
        'OPTIONS': {'context_processors': ['django.template.context_processors.request']},
    }])
    def test_project_list_request_renders_with_role_and_directory_boundaries(self):
        from uuid import UUID
        from . import views_projects

        contract = Contract(id=UUID(int=1), code='TEST-26', name='검증 계약')
        project = Project(id=UUID(int=2), contract=contract, name='검증 프로젝트', status='active')
        for role in ('project_admin', 'project_manager', 'worker', 'viewer'):
            for directory in (True, False):
                for populated in (True, False):
                    with self.subTest(role=role, directory=directory, populated=populated):
                        rows = [project] if populated else []
                        query = MagicMock()
                        query.select_related.return_value = query
                        query.annotate.return_value = query
                        query.order_by.return_value = query
                        query.filter.return_value = query
                        query.__iter__.side_effect = lambda: iter(rows)
                        request = RequestFactory().get('/projects/')
                        request.user = SimpleNamespace(is_authenticated=True, email='fixture@example.invalid')
                        request.session = {
                            'tenant_db_alias': 'tenant_fixture', 'gf_roles': [role],
                            'gf_perms': ['projects.view', 'projects.edit', 'contracts.view'] +
                                        (['directory.view'] if directory else []),
                        }
                        memberships = {str(project.pk): {'member_role': role}} if populated else {}
                        with patch('geoflow_ops.services.entity_access.current_db_alias', return_value='tenant_fixture'), \
                             patch.object(views_projects, '_alias', return_value='tenant_fixture'), \
                             patch.object(Project.objects, 'using', return_value=query) as using, \
                             patch('geoflow_ops.services.project_access.current_employee_id', return_value=None), \
                             patch('geoflow_ops.services.project_access.active_memberships_for_request', return_value=memberships), \
                             patch.object(views_projects, 'project_status_options', return_value=[('active', '진행')]), \
                             patch('geoflow_ops.views_project_members.connections') as connections, \
                             patch('django.urls.reverse', return_value='/fixture/'):
                            cursor = connections.__getitem__.return_value.cursor.return_value.__enter__.return_value
                            cursor.fetchone.return_value = (True,)
                            cursor.fetchall.return_value = [(str(project.pk), '검증 담당자')]
                            response = security_views.project_list(request)
                            response.render()
                            order = query.order_by.call_args_list[0].args
                            self.assertEqual(order[0].expression.name, 'code')
                            self.assertTrue(order[0].descending)
                            self.assertEqual(response.status_code, 200)
                            self.assertEqual(response.context_data['projects'], rows)
                            self.assertEqual(response.context_data['can_create_project'], role in ('project_admin', 'project_manager'))
                            self.assertTrue(all(call.args == ('tenant_fixture',) for call in using.call_args_list))
                            if role in ('worker', 'viewer'):
                                self.assertEqual(query.filter.call_count, 2)
                                query.filter.assert_called_with(pk__in=sorted(memberships))
                            else:
                                query.filter.assert_not_called()
                            if populated:
                                expected = '검증 담당자' if directory else '열람 제한'
                                self.assertIn(expected, response.content.decode())
                            if not directory or not populated:
                                connections.__getitem__.assert_not_called()

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
            self.assertNotIn('confirm_duplicate',form.fields)
            self.assertIsInstance(form.fields['name'].widget,TextInput)
        self.assertNotIn('confirm_single', ContractForm.base_fields)
    def test_changed_templates_compile(self):
        for path in ('projects/project_list.html','projects/project_detail.html','projects/project_form.html','contracts/contract_detail.html'):
            get_template('geoflow_ops/'+path)


class BidDetailAuthorizationTests(TestCase):
    def test_bid_detail_guards_tenant_permission_and_method_before_read(self):
        from types import SimpleNamespace
        from unittest.mock import patch
        from uuid import uuid4
        from django.core.exceptions import PermissionDenied
        from django.http import HttpResponse
        from django.test import RequestFactory
        from geoflow_ops.bids import security_views as bids

        request = RequestFactory().get('/bids/detail/')
        request.user = SimpleNamespace(is_authenticated=True)
        request.session = {'tenant_db_alias':'company_a'}
        with patch('geoflow_ops.services.entity_access.current_db_alias', return_value='company_a'), \
             patch.object(bids, 'gf_has_perm', return_value=False), \
             patch.object(bids.views, 'notice_detail') as read:
            with self.assertRaises(PermissionDenied):
                bids.notice_detail(request, uuid4())
            read.assert_not_called()
        with patch('geoflow_ops.services.entity_access.current_db_alias', return_value='company_b'), \
             patch.object(bids, 'gf_has_perm', return_value=True), \
             patch.object(bids.views, 'notice_detail') as read:
            with self.assertRaises(PermissionDenied):
                bids.notice_detail(request, uuid4())
            read.assert_not_called()
        with patch('geoflow_ops.services.entity_access.current_db_alias', return_value='company_a'), \
             patch.object(bids, 'gf_has_perm', side_effect=lambda request, permission: permission == 'contracts.view'), \
             patch.object(bids.views, 'notice_detail', return_value=HttpResponse('detail')) as read:
            pk = uuid4()
            response = bids.notice_detail(request, pk)
            read.assert_called_once_with(request, 'company_a', pk, can_review=False)
            self.assertIn('no-store', response['Cache-Control'])
            read.reset_mock()
            request.method = 'POST'
            self.assertEqual(bids.notice_detail(request, pk).status_code, 405)
            read.assert_not_called()
