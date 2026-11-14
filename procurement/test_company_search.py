"""Company search boundaries, candidate visibility, and legacy record preservation."""
import importlib
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.db import connections
from django.http import Http404
from django.template import Context, Engine
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from geoflow_ops.bids import profiles
from procurement.models import CollectionRule, InterestCondition, Notice
from procurement.tenant import query_notices, save_review, review_rows


class BadgeTests(SimpleTestCase):
    def test_local_requires_exact_confirmed_city_restriction(self):
        city = dict(id='city', name='충남 아산시', aliases=['충청남도 아산시', '아산시'])
        profile = dict(local_region_id='city')
        for text, expected in [('아산시', True), ('충청남도 아산시', True), ('충남', False),
                               ('충청남도', False), ('아산시, 천안시', False), ('', False), ('전국', False)]:
            self.assertEqual(profiles.local_badge({'region_text':text}, profile, {'region':[city]}),expected)
        for name in ['충청남도', '대전광역시', '세종특별자치시']:
            self.assertFalse(profiles.is_local_region({'name':name}))
        self.assertFalse(profiles.local_badge({'region_text':'아산시'}, {}, {'region':[city]}))

    def test_method_badges_use_fields_not_title(self):
        self.assertEqual(profiles.badges({'title':'협상 직찰 수의시담'}), [])
        self.assertEqual(profiles.badges({'bid_method_name':'직찰', 'award_method_name':'협상에 의한 계약'}), ['직찰','협상'])

    def test_templates_render_company_settings_and_compact_list(self):
        import re
        engine = Engine(libraries={'humanize':'django.contrib.humanize.templatetags.humanize'})
        company = dict(id=str(uuid4()),name='시험회사',address='충남 아산시')
        root = Path(__file__).resolve().parents[1] / 'geoflow_ops/templates/geoflow_ops/bids'
        context = dict(company=company, companies=[company], central_mode=True, can_review=True,
            profile_inherited=True, profile_rules=[], profile_groups=[], local_regions=[],
            profile_sources=[], personal_view='all', notices=[dict(id=str(uuid4()), title='시험 공고',
            memo='보존 기록', saved=True, badges=['관내','협상'])])
        for name in ['notice_list','settings']:
            source = re.sub(r'{% extends .*?%}', '', (root / (name+'.html')).read_text())
            source = re.sub(r'{% url .*?%}', '/bids/', source)
            rendered = engine.from_string(source).render(Context(context))
            self.assertIn('시험회사', rendered)
            self.assertNotIn('name="status"', rendered)
            if name == 'notice_list':
                self.assertNotIn('<th>지역 / 업종</th>', rendered)
                self.assertIn('관심 해제', rendered)
                self.assertIn('보존 기록', rendered)
                self.assertIn('modal fade', rendered)


@override_settings(G2B_CENTRAL_TENANT_ALIASES=('company_a','company_b'))
class CompanyQueryTests(TestCase):
    def test_company_conditions_are_or_sources_apply_only_to_custom_search(self):
        first = InterestCondition.objects.create(kind='keyword',key='first',name='first')
        second = InterestCondition.objects.create(kind='keyword',key='second',name='second')
        a = CollectionRule.objects.create(kind='keyword',value='first',name='first',condition=first)
        b = CollectionRule.objects.create(kind='keyword',value='second',name='second',condition=second,source='kepco')
        g = Notice.objects.create(source='g2b',number='a',order='000',title='a',posted_at=timezone.now(),last_seen_at=timezone.now())
        k = Notice.objects.create(source='kepco',number='b',order='000',title='b',posted_at=timezone.now(),last_seen_at=timezone.now())
        g.rules.add(a); k.rules.add(b)
        profile = dict(condition_ids=[str(first.pk),str(second.pk)],sources=['kepco'])
        with patch('procurement.tenant.review_rows',return_value={}), patch('geoflow_ops.bids.profiles.filters',return_value={}):
            self.assertEqual(set(query_notices('company_a',search_profile=profile)[0]), {k})
            self.assertEqual(set(query_notices('company_a',search_profile=profile,include_all=True)[0]), {g,k})
            profile['sources']=[]
            self.assertEqual(set(query_notices('company_a',search_profile=profile)[0]), {g,k})
            profile['condition_ids']=[]
            self.assertEqual(query_notices('company_a',search_profile=profile)[0].count(),0)
            state={str(g.pk):dict(saved=True,hidden=False)}
            self.assertEqual(set(query_notices('company_a',search_profile=profile,personal_view='saved',personal_state=state)[0]), {g})

    def test_company_profile_regions_do_not_fall_back_to_tenant_filters(self):
        notice = Notice.objects.create(number='region',order='000',title='region',region_known=True,region_text='대전광역시',posted_at=timezone.now(),last_seen_at=timezone.now())
        with patch('procurement.tenant.review_rows',return_value={}), patch('geoflow_ops.bids.profiles.filters',return_value={'region':[dict(id='x',name='충청남도')]}) as filters:
            self.assertFalse(query_notices('company_a',search_profile={},include_all=True,region='x')[0].exists())
            filters.return_value={'region':[dict(id='x',name='대전광역시')]}
            self.assertEqual(set(query_notices('company_a',search_profile={},include_all=True,region='x')[0]), {notice})


@override_settings(G2B_CENTRAL_TENANT_ALIASES=('company_a','company_b'))
class CompanyStorageTests(TestCase):
    databases = {'default','company_a','company_b'}

    def setUp(self):
        if connections['company_a'].vendor != 'postgresql':
            self.skipTest('PostgreSQL company profile migration and ownership rehearsal')
        self.company, self.other = str(uuid4()), str(uuid4())
        for alias in ['company_a','company_b']:
            with connections[alias].cursor() as cur:
                cur.execute('CREATE SCHEMA IF NOT EXISTS ops')
                cur.execute('CREATE TABLE IF NOT EXISTS ops.my_org_units(id uuid PRIMARY KEY,name text,address text)')
                cur.execute(importlib.import_module('geoflow_ops.migrations.0036_bid_interest_foundation').FORWARD_SQL)
                cur.execute(importlib.import_module('geoflow_ops.migrations.0037_central_bid_reviews').SQL)
                cur.execute(importlib.import_module('geoflow_ops.migrations.0038_bid_central_preferences').SQL)
                cur.execute(importlib.import_module('geoflow_ops.migrations.0053_bid_company_search_profiles').SQL)
                cur.execute('INSERT INTO ops.my_org_units(id,name,address) VALUES(%s,%s,%s)', [self.company if alias=='company_a' else self.other,alias,'충남 아산시'])
        self.condition = InterestCondition.objects.create(kind='keyword',key='gis',name='GIS')

    def test_independent_company_and_tenant_settings_and_explicit_empty(self):
        with connections['company_a'].cursor() as cur:
            cur.execute('INSERT INTO ops.my_org_units(id,name) VALUES(%s,%s)',[self.other,'other company'])
        first = dict(condition_ids=[str(self.condition.pk)],selections={},sources=['kepco'],local_region_id='')
        profiles.save('company_a',self.company,first)
        profiles.save('company_a',self.other,dict(condition_ids=[],selections={},sources=[]))
        self.assertEqual(profiles.effective('company_a',self.company)[0]['condition_ids'], [str(self.condition.pk)])
        self.assertEqual(profiles.effective('company_a',self.other)[0]['condition_ids'], [])
        self.assertIsNone(profiles.load('company_b',self.other))
        with self.assertRaises(Http404):
            profiles.save('company_b',self.company,first)
        first['selections']={'region':[str(uuid4())]}
        with self.assertRaises(ValueError):
            profiles.save('company_a',self.company,first)
        self.assertEqual(profiles.load('company_a',self.company)['sources'], ['kepco'])
        # An empty company selection is never treated as permission to use central DB.
        with self.assertRaises(ValueError):
            profiles.context('default',self.company)

    def test_memo_update_preserves_old_status_and_normal_list_no_longer_hides_excluded(self):
        n=Notice.objects.create(number='memo',order='000',title='memo',posted_at=timezone.now(),last_seen_at=timezone.now())
        save_review('company_a',n.pk,status='excluded',memo='old',updated_by='tester')
        save_review('company_a',n.pk,status=None,memo='new',updated_by='tester')
        self.assertEqual(review_rows('company_a')[str(n.pk)], dict(review_status='excluded',memo='new'))
        self.assertTrue(query_notices('company_a',include_all=True,include_excluded=True)[0].filter(pk=n.pk).exists())
        self.assertEqual(review_rows('company_b'),{})
