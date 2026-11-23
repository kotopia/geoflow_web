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
                else:
                    cur.execute("PRAGMA database_list")
                    if "bid" not in {row[1] for row in cur.fetchall()}:
                        cur.execute("ATTACH DATABASE ':memory:' AS bid")
                    cur.execute('''CREATE TABLE bid.tenant_state(origin text,notice_id text,
                        saved boolean DEFAULT false,hidden boolean DEFAULT false,updated_at text,
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
