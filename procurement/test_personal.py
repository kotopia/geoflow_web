"""Shared visibility, pagination and tenant isolation regressions."""
import importlib
from datetime import timedelta
from unittest.mock import patch
from uuid import uuid4

from django.core.exceptions import PermissionDenied
from django.db import connections
from django.test import TestCase, RequestFactory, override_settings
from django.utils import timezone

from geoflow_ops.bids import tenant_state, repository
from .models import CollectionRule, Notice
from .tenant import query_notices, list_notices
from .preferences import add_keyword


@override_settings(G2B_CENTRAL_TENANT_ALIASES=('company_a', 'company_b'))
class PersonalStateTests(TestCase):
    databases = {'default', 'company_a', 'company_b'}

    @classmethod
    def setUpTestData(cls):
        for alias in ('company_a', 'company_b'):
            with connections[alias].cursor() as cur:
                if connections[alias].vendor == 'postgresql':
                    cur.execute('CREATE SCHEMA IF NOT EXISTS bid')
                    cur.execute(importlib.import_module('geoflow_ops.migrations.0051_bid_personal_state').SQL)
                    cur.execute(importlib.import_module('geoflow_ops.migrations.0055_bid_tenant_state').SQL)
                    cur.execute(importlib.import_module('geoflow_ops.migrations.0057_bid_progress').SQL)
                else:
                    cur.execute("PRAGMA database_list")
                    if "bid" not in {row[1] for row in cur.fetchall()}:
                        cur.execute("ATTACH DATABASE ':memory:' AS bid")
                    cur.execute('''CREATE TABLE bid.tenant_state(origin text,notice_id text,
                        saved boolean DEFAULT false,hidden boolean DEFAULT false,updated_at text,registered_at timestamp,submitted_at timestamp,
                        PRIMARY KEY(origin,notice_id))''')

    def setUp(self):
        self.user = str(uuid4())
        self.other = str(uuid4())
        self.notice = Notice.objects.create(number='personal-test', order='000', title='GIS test',
            posted_at=timezone.now(), close_at=timezone.now()+timedelta(days=1), last_seen_at=timezone.now())
        self.pk = str(self.notice.pk)

    def test_shared_save_hide_restore_unsave_and_tenant_isolation(self):
        tenant_state.save('company_a', self.user, 'central', [self.pk], 'save')
        tenant_state.save('company_a', self.user, 'central', [self.pk], 'hide')
        state = tenant_state.rows('company_a', self.user, 'central')
        self.assertEqual(state[self.pk], {'saved': True, 'hidden': True})
        self.assertEqual(tenant_state.rows('company_a', self.other, 'central'), state)
        self.assertEqual(tenant_state.rows('company_b', self.user, 'central'), {})
        self.assertEqual(tenant_state.rows('company_a', self.user, 'legacy'), {})
        tenant_state.save('company_a', self.other, 'central', [self.pk], 'restore')
        self.assertEqual(tenant_state.rows('company_a', self.user, 'central')[self.pk], {'saved': True, 'hidden': False})
        tenant_state.save('company_a', self.other, 'central', [self.pk], 'unsave')
        self.assertEqual(tenant_state.rows('company_a', self.user, 'central')[self.pk], {'saved': False, 'hidden': False})
        self.assertTrue(Notice.objects.filter(pk=self.pk).exists())

    def test_postgres_migrates_conflicting_personal_states_without_losing_interest(self):
        if connections['company_a'].vendor != 'postgresql':
            self.skipTest('PostgreSQL aggregation migration rehearsal')
        for alias in ('company_a', 'company_b'):
            with connections[alias].cursor() as cur:
                cur.execute('DROP TABLE bid.tenant_state')
                cur.execute("""INSERT INTO bid.personal_state(user_id,origin,notice_id,saved,hidden)
                    VALUES (%s,'central',%s,true,true),(%s,'central',%s,false,false),
                           (%s,'legacy',%s,false,true)""",
                    [self.user,self.pk,self.other,self.pk,self.user,self.pk])
                cur.execute(importlib.import_module('geoflow_ops.migrations.0055_bid_tenant_state').SQL)
                cur.execute('SELECT count(*) FROM bid.personal_state')
                self.assertEqual(cur.fetchone()[0], 3)
            self.assertEqual(tenant_state.rows(alias,self.other,'central')[self.pk], {'saved':True,'hidden':False})
            self.assertEqual(tenant_state.rows(alias,self.other,'legacy')[self.pk], {'saved':False,'hidden':True})
        tenant_state.save('company_a',self.other,'central',[self.pk],'unsave')
        self.assertTrue(tenant_state.rows('company_b',self.user,'central')[self.pk]['saved'])

    def test_retry_reconciles_newer_legacy_writes_and_preserves_newer_shared_state(self):
        if connections['company_a'].vendor != 'postgresql':
            self.skipTest('PostgreSQL deployment retry rehearsal')
        with connections['company_a'].cursor() as cur:
            cur.execute("""INSERT INTO bid.personal_state(user_id,origin,notice_id,saved,hidden,updated_at)
                VALUES (%s,'central',%s,true,true,CURRENT_TIMESTAMP - interval '2 hours')""",
                [self.user,self.pk])
            tenant_state.refresh_personal_snapshot(cur)
        self.assertEqual(tenant_state.rows('company_a',self.user,'central')[self.pk], {'saved':True,'hidden':True})
        tenant_state.save('company_a',self.user,'central',[self.pk],'unsave')
        with connections['company_a'].cursor() as cur:
            tenant_state.refresh_personal_snapshot(cur)
        self.assertFalse(tenant_state.rows('company_a',self.user,'central')[self.pk]['saved'])
        with connections['company_a'].cursor() as cur:
            cur.execute("UPDATE bid.personal_state SET saved=false,hidden=false,updated_at=CURRENT_TIMESTAMP + interval '1 hour'")
            tenant_state.refresh_personal_snapshot(cur)
            tenant_state.refresh_personal_snapshot(cur)
        self.assertEqual(tenant_state.rows('company_a',self.user,'central')[self.pk], {'saved':False,'hidden':False})
        self.assertEqual(tenant_state.rows('company_b',self.user,'central'), {})

    def test_progress_shared_badge_priority_undo_and_isolation(self):
        def state(alias='company_a', origin='central'):
            return tenant_state.progress_rows(alias,self.other,origin,[self.pk]).get(self.pk,{})
        tenant_state.save('company_a',self.user,'central',[self.pk],'save')
        tenant_state.save_progress('company_a',self.user,'central',self.pk,'register')
        self.assertEqual(state()['progress_badge'],'참가')
        tenant_state.save_progress('company_a',self.user,'central',self.pk,'submit')
        self.assertEqual(state()['progress_badge'],'투찰')
        self.assertTrue(state()['registered_at'])
        self.assertEqual(state('company_b'),{})
        self.assertEqual(state(origin='legacy'),{})
        tenant_state.save_progress('company_a',self.other,'central',self.pk,'unsubmit')
        self.assertEqual(state()['progress_badge'],'참가')
        tenant_state.save_progress('company_a',self.other,'central',self.pk,'unregister')
        self.assertEqual(state()['progress_badge'],'')
        self.assertTrue(tenant_state.rows('company_a',self.user,'central')[self.pk]['saved'])
        # Registration is not mandatory for every notice; bidding does not invent registration.
        tenant_state.save_progress('company_a',self.user,'central',self.pk,'submit')
        self.assertIsNone(state()['registered_at'])
        for alias, pk, action in [('default',self.pk,'submit'),('company_a',str(uuid4()),'submit'),('company_a',self.pk,'opened')]:
            with self.assertRaises(ValueError):
                tenant_state.save_progress(alias,self.user,'central',pk,action)
        # The view-only bookmarking endpoint must not accept progress actions.
        with self.assertRaises(ValueError):
            tenant_state.save('company_a',self.user,'central',[self.pk],'submit')

    def test_progress_endpoint_requires_write_permission_and_post(self):
        import sys
        from types import ModuleType
        context = ModuleType('geoflow_ops.services.entity_access')
        context.require_tenant_context = lambda request: 'company_a'
        with patch.dict(sys.modules, {'geoflow_ops.services.entity_access': context}):
            from geoflow_ops.bids import security_views
        request = RequestFactory().post('/bids/progress/', {'action':'submit'})
        request.user = type('User',(),{'is_authenticated':True})()
        with patch.object(security_views,'require_tenant_context',return_value='company_a'), patch.object(security_views,'gf_has_perm',side_effect=lambda req,p:p=='contracts.view'), patch.object(security_views.views,'progress_save') as save:
            with self.assertRaises(PermissionDenied):
                security_views.progress_save(request,self.notice.pk)
            save.assert_not_called()
        request.method='GET'
        self.assertEqual(security_views.progress_save(request,self.notice.pk).status_code,405)

    def test_ajax_progress_returns_state_without_redirect(self):
        import json
        from geoflow_ops.bids import views
        request = RequestFactory().post('/bids/progress/', {'action':'register'}, HTTP_X_REQUESTED_WITH='XMLHttpRequest')
        with patch.object(views.tenant_state,'user_id',return_value=self.user):
            response = views.progress_save(request,'company_a',self.notice.pk)
        self.assertEqual(response.status_code,200)
        body = json.loads(response.content)
        self.assertEqual(body['progress_badge'],'참가')
        self.assertEqual(body['timeline'][0]['action'],'unregister')
        self.assertTrue(body['timeline'][0]['completed_label'].startswith('완료 기록'))

    def test_saved_bid_calendar_projection_tracks_changes_and_tenant_scope(self):
        from geoflow_ops.bids.calendar import events
        from datetime import date
        self.notice.summary = {'open_at':'2026-11-25T11:00:00+09:00'}
        self.notice.raw = {'notice':{'bidQlfctRgstDt':'2026-11-24 18:00:00'}}
        self.notice.close_at = timezone.datetime(2026,11,25,1,tzinfo=timezone.get_fixed_timezone(0))
        self.notice.save()
        args = (date(2026,11,1),date(2026,12,1))
        self.assertEqual(events('company_a',self.user,*args),[])
        tenant_state.save('company_a',self.user,'central',[self.pk],'save')
        rows = events('company_a',self.other,*args)
        self.assertEqual(len(rows),1)
        self.assertEqual(rows[0]['title'],self.notice.title)
        self.assertTrue(all(not r['allDay'] for r in rows))
        self.assertTrue(all('notice='+self.pk in r['url'] for r in rows))
        self.assertEqual(events('company_b',self.user,*args),[])
        self.assertEqual(events('company_a',self.user,date(2026,12,1),date(2027,1,1)),[])
        tenant_state.save_progress('company_a',self.user,'central',self.pk,'submit')
        rows = events('company_a',self.user,*args)
        self.assertFalse(next(r for r in rows if r['extendedProps']['event_type']=='open_at')['extendedProps']['history'])
        self.notice.summary = {'open_at':'2026-11-26T11:00:00+09:00'}
        self.notice.save()
        self.assertIn('2026-11-26',next(r for r in events('company_a',self.user,*args) if r['extendedProps']['event_type']=='open_at')['start'])
        tenant_state.save('company_a',self.user,'central',[self.pk],'hide')
        self.assertEqual(events('company_a',self.user,*args),[])
        tenant_state.save('company_a',self.user,'central',[self.pk],'restore')
        self.notice.summary['notice_status']='cancelled'
        self.notice.save()
        self.assertEqual(events('company_a',self.user,*args),[])
        self.notice.summary={}
        self.notice.save()
        tenant_state.save('company_a',self.user,'central',[self.pk],'unsave')
        self.assertEqual(events('company_a',self.user,*args),[])

    def test_kepco_calendar_does_not_invent_missing_dates(self):
        from geoflow_ops.bids.calendar import events
        from datetime import date
        self.notice.source='kepco'
        self.notice.summary={'open_at':'invalid'}
        self.notice.raw={'notice':{'bidQlfctRgstDt':'2026-11-24 18:00:00'}}
        self.notice.close_at=timezone.datetime(2026,11,25,1,tzinfo=timezone.get_fixed_timezone(0))
        self.notice.save()
        tenant_state.save('company_a',self.user,'central',[self.pk],'save')
        rows=events('company_a',self.user,date(2026,11,1),date(2026,12,1))
        self.assertEqual(rows,[])

    def test_invalid_batch_is_atomic_and_scope_fails_closed(self):
        for alias, actor, ids, action in [('default', self.user, [self.pk], 'hide'),
                ('company_a', '', [self.pk], 'hide'), ('company_a', self.user, [self.pk,str(uuid4())], 'hide'),
                ('company_a', self.user, [self.pk]*31, 'hide'), ('company_a', self.user, [self.pk], 'delete')]:
            with self.assertRaises(ValueError):
                tenant_state.save(alias, actor, 'central', ids, action)
        self.assertEqual(tenant_state.rows('company_a', self.user, 'central'), {})
        with self.assertRaises(PermissionDenied):
            tenant_state.user_id(RequestFactory().get('/bids/'))

    def test_visibility_before_count_pagination_and_saved_ignores_changed_conditions(self):
        rule = CollectionRule.objects.create(kind='keyword', value='GIS', name='GIS')
        self.notice.rules.add(rule)
        state={self.pk:{'saved':True,'hidden':True}}
        with patch('procurement.tenant.review_rows', return_value={}), \
             patch('procurement.tenant.load_filters', return_value={}), \
             patch('procurement.tenant.selected_ids', return_value=[str(rule.pk)]):
            self.assertEqual(query_notices('company_a', personal_state=state)[0].count(),0)
            self.assertEqual(query_notices('company_a', personal_state=state,personal_view='hidden')[0].count(),1)
            self.assertEqual(list_notices('company_a',personal_state=state),[])
            Notice.objects.filter(pk=self.pk).update(close_at=timezone.now()-timedelta(hours=1))
            self.assertEqual(query_notices('company_a',include_closed=False)[0].count(),0)
            self.assertEqual(query_notices('company_a',include_closed=True)[0].count(),1)
            Notice.objects.filter(pk=self.pk).update(close_at=None)
            self.assertEqual(query_notices('company_a',include_closed=False)[0].count(),1)
            state[self.pk]['hidden']=False
            with patch('procurement.tenant.selected_ids', return_value=[]):
                self.assertEqual(query_notices('company_a',personal_state=state,personal_view='saved')[0].count(),1)

    def test_keyword_reuses_case_insensitive_rule_never_reactivates(self):
        rule = CollectionRule.objects.create(kind='keyword',value='gis',name='GIS')
        with patch('procurement.preferences.selected_conditions',return_value=[]), patch('procurement.preferences.save') as save:
            add_keyword('company_a',' GIS ')
            self.assertEqual(CollectionRule.objects.count(),2)
            rule.refresh_from_db()
            self.assertIn(str(rule.condition_id),save.call_args.args[1])
            CollectionRule.objects.filter(condition_id=rule.condition_id).update(active=False)
            with self.assertRaises(ValueError):
                add_keyword('company_a','GIS')

    def test_legacy_filter_uses_bound_ids_and_deadline(self):
        where,params=repository._notice_filters(query='',review_status='',include_all=False,
            personal_state={self.pk:{'saved':False,'hidden':True}},include_closed=False)
        self.assertIn(self.pk,params)
        self.assertNotIn(self.pk,' '.join(where))
        self.assertIn('COALESCE(n.bid_close_at,n.open_at)>now()', ' '.join(where))
