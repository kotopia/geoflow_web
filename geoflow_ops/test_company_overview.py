from datetime import date
from decimal import Decimal
from importlib import import_module
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from uuid import uuid4
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connections, IntegrityError, transaction
from django.db.migrations.state import ProjectState, ModelState
from django.http import HttpResponse
from django.template.loader import render_to_string
from django.test import RequestFactory, override_settings
from django.urls import path, include
from .models import MyOrgUnit, ProcessEvent, Attachment
from .company_models import CompanyProfile, CompanyRegistration, CompanyRevenue, CompanyHeadcount, CompanyCredit, CompanyEvidence
from .company_forms import RevenueForm, CreditForm, HeadcountForm, ProfileForm
from .services import company_overview as service
from . import views_company

# Only local test routes; render real AdminKit base/components without live menus.
urlpatterns = [path('',include(([
    path('companies/',views_company.home,name='myinfo_orgunit_list'),
    path('companies/new/',lambda r: HttpResponse(),name='myinfo_orgunit_create'),
    path('companies/<uuid:pk>/',views_company.overview,name='myinfo_orgunit_detail'),
    path('companies/<uuid:pk>/edit/',views_company.edit,name='myinfo_orgunit_update'),
    path('companies/<uuid:pk>/departments/',lambda r: HttpResponse(),name='myinfo_department_save'),
    path('companies/<uuid:pk>/grades/',lambda r: HttpResponse(),name='myinfo_job_grade_save'),
    path('companies/<uuid:pk>/positions/',lambda r: HttpResponse(),name='myinfo_job_position_save'),
], 'tenant'),namespace='tenant'))]


def request(method='get',data=None,url='/companies/'):
    req = getattr(RequestFactory(),method)(url,data or {})
    req.user = SimpleNamespace(is_authenticated=True,pk=uuid4())
    req.session = {'tenant_db_alias':'company_test'}
    return req


class CompanyRulesTests(TestCase):
    def test_negative_revenue_is_rejected_but_zero_is_real(self):
        data={'year':2025,'fiscal_on':'2025-12-31','amount':'-1','source':'재무제표'}
        self.assertFalse(RevenueForm(data).is_valid())
        data['amount']='0'
        self.assertTrue(RevenueForm(data).is_valid())

    def test_fiscal_year_mismatch_rejected(self):
        self.assertFalse(RevenueForm({'year':2025,'fiscal_on':'2024-12-31','amount':10,'source':'보고서'}).is_valid())

    def test_credit_expiry_before_evaluation_rejected(self):
        form=CreditForm({'agency':'기관','rating_type':'기업신용','grade':'A','evaluated_on':'2025-05-01','expires_on':'2025-01-01'})
        self.assertFalse(form.is_valid())
        self.assertIn('expires_on',form.errors)

    def test_current_headcount_cannot_be_manually_overwritten(self):
        from django.utils import timezone
        form=HeadcountForm({'year':timezone.localdate().year,'count':99,'source':'수기'})
        self.assertFalse(form.is_valid())

    def test_profile_form_does_not_query_central_for_primary(self):
        with patch.object(connections['default'],'cursor',side_effect=AssertionError('central DB accessed')):
            self.assertTrue(ProfileForm({'node_kind':'company','is_primary':'on'}).is_valid())

    def test_parent_self_or_cycle_rejected(self):
        company, parent=uuid4(),uuid4()
        with self.assertRaises(ValidationError): service.validate_parent('company_test',company,company,'company')
        with patch.object(MyOrgUnit,'objects') as orgs, patch.object(CompanyProfile,'objects') as profiles:
            orgs.using.return_value.filter.return_value.exists.return_value=True
            profiles.using.return_value.filter.return_value.first.return_value=SimpleNamespace(node_kind='company',parent_id=company)
            with self.assertRaises(ValidationError): service.validate_parent('company_test',company,parent,'company')

    def test_branch_requires_parent(self):
        with self.assertRaises(ValidationError): service.validate_parent('company_test',uuid4(),None,'branch')

    def test_company_with_children_cannot_become_branch(self):
        with patch.object(CompanyProfile,'objects') as profiles:
            profiles.using.return_value.filter.return_value.exists.return_value=True
            with self.assertRaises(ValidationError):
                service.validate_parent('company_test',uuid4(),uuid4(),'branch')

    def test_missing_series_is_null_and_finance_not_queried(self):
        with patch.object(CompanyRevenue,'objects') as revenue, patch.object(CompanyHeadcount,'objects') as head:
            head.using.return_value.filter.return_value.values_list.return_value=[]
            rows=service.annual_series('company_test',uuid4(),3,finance=False)
            self.assertEqual(len(rows),3)
            self.assertTrue(all(row['revenue'] is None and row['headcount'] is None for row in rows))
            revenue.using.assert_not_called()

    def test_evidence_foreign_company_or_deleted_rejected(self):
        with patch.object(service,'evidence_candidates') as candidates:
            candidates.return_value.filter.return_value.values_list.return_value=[]
            with self.assertRaises(ValidationError): service.validate_evidence('company_test',uuid4(),'registration',[uuid4()])

    def test_invalid_evidence_uuid_rejected(self):
        with self.assertRaises(ValidationError): service.validate_evidence('company_test',uuid4(),'registration',['bad'])


class CompanyBoundaryTests(TestCase):
    def test_feature_disabled_does_not_access_database(self):
        with override_settings(GEOFLOW_COMPANY_OVERVIEW_ENABLED=False), patch.object(views_company,'require_tenant_context',return_value='company_test'), patch.object(MyOrgUnit,'objects') as orgs:
            from django.http import Http404
            with self.assertRaises(Http404): views_company.access(request())
            orgs.using.assert_not_called()

    def test_edit_financial_section_denied_before_query(self):
        with patch.object(views_company,'access',return_value=('company_test',SimpleNamespace(pk=uuid4()))), patch.object(views_company,'can_edit_finance',return_value=False), patch.object(CompanyRevenue,'objects') as revenues:
            with self.assertRaises(PermissionDenied): views_company.edit(request(url='/companies/?section=revenue'),uuid4())
            revenues.using.assert_not_called()

    def test_tenant_mismatch_denied(self):
        from .services.entity_access import require_tenant_context
        with patch('geoflow_ops.services.entity_access.current_db_alias',return_value='other_tenant'):
            with self.assertRaises(PermissionDenied): require_tenant_context(request())

    def test_directory_permission_required(self):
        with patch.object(views_company,'require_tenant_context',return_value='company_test'),patch.object(views_company,'gf_has_perm',return_value=False):
            with self.assertRaises(PermissionDenied): views_company.access(request())

    def test_automatic_event_cannot_be_changed_through_shared_api(self):
        from .services.entity_access import get_event_for_access
        with patch.object(ProcessEvent,'objects') as events:
            events.using.return_value.filter.return_value.first.return_value=SimpleNamespace(payload={'company_source_id':str(uuid4())})
            self.assertIsNone(get_event_for_access(request(),'company_test',uuid4(),write=True))

    def test_financial_evidence_requires_both_permissions(self):
        from .services.entity_access import authorize_attachment_read,authorize_attachment_write
        att=SimpleNamespace(purpose='company_financial',entity_type='orgunit',entity_id=uuid4())
        with patch('geoflow_ops.services.entity_access.can_view_finance',return_value=True),patch('geoflow_ops.services.entity_access.authorize_scope_read',return_value=False):
            self.assertFalse(authorize_attachment_read(request(),'company_test',att))
        with patch('geoflow_ops.services.entity_access.can_edit_finance',return_value=False),patch('geoflow_ops.services.entity_access.authorize_scope_write',return_value=True):
            self.assertFalse(authorize_attachment_write(request(),'company_test','orgunit',att.entity_id,attachment=att))

    def test_financial_upload_denied_before_s3(self):
        from . import views_uploads
        for view in [views_uploads.presign_put,views_uploads.commit]:
            req=request('post',url='/uploads/')
            payload={'entity_type':'orgunit','entity_id':str(uuid4()),'purpose':'company_financial','filename':'evidence.pdf','original_name':'evidence.pdf','mime_type':'application/pdf','size_bytes':100,'document_title':'재무제표','object_key':'tenants/company_test/nope.pdf'}
            with patch.object(views_uploads,'require_tenant_context',return_value='company_test'),patch.object(views_uploads,'_parse_json',return_value=payload),patch('geoflow_ops.services.finance_access.can_edit_finance',return_value=False),patch.object(views_uploads,'head_private_object') as head,patch.object(views_uploads,'generate_presigned_put_url') as sign:
                self.assertEqual(view(req).status_code,403)
                head.assert_not_called();sign.assert_not_called()


class CompanyTemplateTests(TestCase):
    def test_real_templates_escape_content_and_do_not_render_edit_on_overview(self):
        obj=MyOrgUnit(id=uuid4(),name='<script>alert(1)</script>')
        html=render_to_string('geoflow_ops/myinfo/company_overview.html',{'obj':obj,'companies':[obj],'headcount':0,'series':[],'years':5,'registrations':[],'events':[]})
        self.assertIn('&lt;script&gt;',html)
        self.assertNotIn('<script>alert(1)</script>',html)
        self.assertNotIn('method="post"',html)
        self.assertIn('control/css/light.css',html)
        self.assertIn('재무 조회 권한',html)
        self.assertIn('company-headcount-chart',html)

    def test_editor_has_separate_form_and_finance_tabs_hidden(self):
        obj=MyOrgUnit(id=uuid4(),name='테스트기업')
        html=render_to_string('geoflow_ops/myinfo/company_edit.html',{'obj':obj,'kind':'basic','form':ProfileForm(),'companies':[obj]})
        self.assertIn('company-fact-form',html)
        self.assertNotIn('href="?section=revenue"',html)


class CompanyDatabaseTests(TestCase):
    """Real ORM + migration rehearsal; only enabled in disposable CI."""
    @classmethod
    def setUpClass(cls):
        cls.connection=connections['company_test']
        with cls.connection.cursor() as cur:
            cur.execute('CREATE SCHEMA ops; CREATE SCHEMA hr')
            cur.execute('CREATE TABLE hr.employee_profile (id uuid PRIMARY KEY, org_unit_id uuid, hire_date date, term_date date, status text, is_deleted boolean DEFAULT false)')
        with cls.connection.schema_editor() as editor:
            for model in [MyOrgUnit,ProcessEvent,Attachment]: editor.create_model(model)
        cls.before=ProjectState()
        for model in [MyOrgUnit,ProcessEvent,Attachment]: cls.before.add_model(ModelState.from_model(model))
        cls.migration=import_module('geoflow_ops.migrations.0049_company_overview').Migration('0049_company_overview','webgisapp')
        with cls.connection.schema_editor() as editor:
            cls.after=cls.migration.apply(cls.before,editor)

    @classmethod
    def tearDownClass(cls):
        with cls.connection.schema_editor() as editor:
            cls.migration.unapply(cls.before,editor)
        with cls.connection.cursor() as cur:
            cur.execute("SELECT to_regclass('ops.company_profile'),to_regclass('ops.my_org_units')")
            new,legacy=cur.fetchone()
            assert new is None and legacy is not None
            cur.execute('DROP SCHEMA hr CASCADE; DROP SCHEMA ops CASCADE')

    def setUp(self):
        self.company=MyOrgUnit.objects.using('company_test').create(name='Synthetic company')
        self.other=MyOrgUnit.objects.using('company_test').create(name='Other synthetic company')

    def test_sync_is_idempotent_and_evidence_links_persist(self):
        row=CompanyRegistration.objects.using('company_test').create(company=self.company,kind='registration',name='측량업',occurred_on=date(2025,1,1))
        service.sync_source_event('company_test',row,'registration','ci')
        event_id=row.event_id
        row.name='측량업 정정';row.save(using='company_test')
        service.sync_source_event('company_test',row,'registration','ci')
        self.assertEqual(row.event_id,event_id)
        self.assertEqual(ProcessEvent.objects.using('company_test').filter(scope_id=self.company.pk).count(),1)
        self.assertIn('정정',ProcessEvent.objects.using('company_test').get(pk=event_id).title)
        att=Attachment.objects.using('company_test').create(entity_type='orgunit',entity_id=self.company.pk,purpose='business_registration',object_key=str(uuid4()),original_name='synthetic.pdf',size_bytes=1)
        ids=service.validate_evidence('company_test',self.company.pk,'registration',[att.pk])
        service.replace_evidence('company_test',row,'registration',ids)
        self.assertEqual(service.record_evidence('company_test',self.company.pk,'registration',row.pk).count(),1)
        with self.assertRaises(ValidationError): service.validate_evidence('company_test',self.other.pk,'registration',[att.pk])
        service.replace_evidence('company_test',row,'registration',set())
        self.assertTrue(Attachment.objects.using('company_test').filter(pk=att.pk).exists())

    def test_database_enforces_unique_year_and_primary_rating(self):
        CompanyRevenue.objects.using('company_test').create(company=self.company,year=2025,fiscal_on=date(2025,12,31),amount=0,source='ci')
        with self.assertRaises(IntegrityError),transaction.atomic(using='company_test'):
            CompanyRevenue.objects.using('company_test').create(company=self.company,year=2025,fiscal_on=date(2025,12,31),amount=1,source='ci')
        for primary in [True,False]:
            CompanyCredit.objects.using('company_test').create(company=self.company,agency='Agency',rating_type='type',grade='A',evaluated_on=date(2025,1,1),representative=primary)
        with self.assertRaises(IntegrityError),transaction.atomic(using='company_test'):
            CompanyCredit.objects.using('company_test').create(company=self.company,agency='Other',rating_type='type',grade='B',evaluated_on=date(2025,1,1),representative=True)

    def test_hr_count_and_historical_gaps(self):
        rows=[(self.company.pk,None,None,'active',False),(self.company.pk,None,date(2020,1,1),'active',False),(self.company.pk,date(2200,1,1),None,'active',False),(self.company.pk,None,None,'retired',False),(self.company.pk,None,None,'active',True),(self.other.pk,None,None,'active',False)]
        with self.connection.cursor() as cur:
            for company,hire,term,status,deleted in rows:
                cur.execute('INSERT INTO hr.employee_profile VALUES (%s,%s,%s,%s,%s,%s)',[uuid4(),company,hire,term,status,deleted])
        with patch('geoflow_ops.views_employee_profile._retired_status_codes',return_value=['retired']):
            self.assertEqual(service.current_headcount('company_test',self.company.pk),1)
        series=service.annual_series('company_test',self.company.pk,5,finance=True)
        self.assertTrue(all(row['headcount'] is None for row in series))

    def test_registration_save_rolls_back_if_evidence_is_foreign(self):
        req=request('post',{'kind':'registration','name':'Permit','occurred_on':'2025-01-01','status':'active','evidence':[str(uuid4())]},url='/companies/?section=registration')
        with patch.object(views_company,'access',return_value=('company_test',self.company)),patch.object(views_company,'can_edit_finance',return_value=False),patch.object(views_company,'can_view_finance',return_value=False):
            response=views_company.edit(req,self.company.pk)
        self.assertEqual(response.status_code,200)
        self.assertFalse(CompanyRegistration.objects.using('company_test').filter(company=self.company).exists())

    def test_save_record_and_renewal_keep_original_event(self):
        def save(data,url):
            with patch.object(views_company,'access',return_value=('company_test',self.company)),patch.object(views_company,'can_edit_finance',return_value=False),patch.object(views_company,'can_view_finance',return_value=False),patch.object(views_company.messages,'success'):
                return views_company.edit(request('post',data,url=url),self.company.pk)
        data={'kind':'registration','name':'Permit','occurred_on':'2025-01-01','status':'active'}
        self.assertEqual(save(data,'/companies/?section=registration').status_code,302)
        first=CompanyRegistration.objects.using('company_test').get(company=self.company)
        data['occurred_on']='2026-01-01'
        self.assertEqual(save(data,f'/companies/?section=registration&record={first.pk}&renew=1').status_code,302)
        self.assertEqual(CompanyRegistration.objects.using('company_test').filter(company=self.company).count(),2)
        self.assertEqual(ProcessEvent.objects.using('company_test').filter(scope_id=self.company.pk).count(),2)
        self.assertEqual(ProcessEvent.objects.using('company_test').get(pk=first.event_id).occurred_at,date(2025,1,1))
