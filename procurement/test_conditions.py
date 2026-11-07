import importlib
import json
from io import StringIO
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.db import connections, connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TestCase, TransactionTestCase, override_settings
from django.utils import timezone

from .conditions import bind_rule, canonical_ids, resolve_rule_ids
from .models import CollectionRule, InterestCondition, Notice
from .preferences import selected_ids, selected_conditions, save
from .service import store_notice, rule_matches
from .tenant import query_notices, list_notices
from .kepco import adapt
from geoflow_ops.bids.matcher import keyword_matches


class LogicalConditionTests(TestCase):
    def setUp(self):
        self.g2b = CollectionRule.objects.create(source='g2b', kind='industry', value='5023', name='나라장터 - 공공측량업')
        self.kepco = CollectionRule.objects.create(source='kepco', kind='industry', value='공공측량업', name='한전 - 공공측량업')
        self.condition = bind_rule(self.g2b)
        bind_rule(self.kepco)
        self.now = timezone.now()

    def notice(self, source, number, rule):
        item = Notice.objects.create(source=source, number=number, order='0', title='공공측량 용역',
                                     posted_at=self.now, last_seen_at=self.now, summary={'source':source, 'source_label':rule.get_source_display()})
        item.rules.add(rule)
        return item

    def test_grouping_is_identity_mapping_not_display_names(self):
        self.assertEqual(self.condition.pk, self.kepco.condition_id)
        self.assertEqual(self.condition.name, '공공측량업')
        unrelated = CollectionRule.objects.create(source='kepco', kind='industry', value='실제 다른 면허', name='공공측량업')
        self.assertNotEqual(bind_rule(unrelated).pk, self.condition.pk)
        self.assertFalse(InterestCondition.objects.filter(name='측지측량업').exists())

    def test_legacy_selection_expands_current_and_future_sources_without_writes(self):
        old = [str(self.g2b.pk)]
        self.assertEqual(canonical_ids(old), [str(self.condition.pk)])
        self.assertEqual(set(resolve_rule_ids(old)), {str(self.g2b.pk), str(self.kepco.pk)})
        future = CollectionRule.objects.create(source='future', kind='industry', value='provider-code', name='내부 명칭', condition=self.condition)
        self.assertIn(str(future.pk), resolve_rule_ids(old))
        self.assertEqual(old, [str(self.g2b.pk)])

    def test_one_logical_choice_returns_both_sources_distinct_and_preserves_source_labels(self):
        g2b = self.notice('g2b', 'g2b-1', self.g2b)
        kepco = self.notice('kepco', 'kepco-1', self.kepco)
        other = CollectionRule.objects.create(source='kepco', kind='keyword', value='측량', name='측량')
        kepco.rules.add(other)
        with patch('procurement.preferences.stored_ids', return_value=[str(self.condition.pk)]), \
             patch('procurement.tenant.review_rows', return_value={}), patch('procurement.tenant.load_filters', return_value={}):
            self.assertEqual(set(query_notices('company_a')[0].values_list('pk',flat=True)), {g2b.pk,kepco.pk})
            self.assertEqual({row['source_label'] for row in list_notices('company_a')}, {'나라장터','한국전력'})

    def test_keyword_existing_normalization(self):
        for keyword in ('지하시설물','지하 시설물'):
            for title in ('지하시설물','지하 시설물','지하시설물도','지하 시설물도'):
                self.assertTrue(keyword_matches(keyword,title))
        self.assertFalse(keyword_matches('GIS','GIST'))

    def test_problem_notice_public_text_regression_not_claimed_as_live_api_response(self):
        # Title and qualification terms cross-checked against the publicly reproduced
        # notice https://work.00data.kr/projects/KPE012607882 . The API envelope below
        # is a fixture, not an observed KEPCO API response or production DB record.
        row = adapt({'companyId':'COM01','itemType':'Service','no':'E012607882',
                     'name':'서산지역 전기공급시설 전력구공사(서산-성연) 지하시설물도 작성용역',
                     'noticeDate':self.now.strftime('%Y%m%d'),
                     'bidAttendRestrict':'공공측량업(또는 측지측량업), 수치지도제작업, 지하시설물측량업'})
        details = {'regions':[], 'industries':[], 'products':[]}
        keyword = CollectionRule.objects.create(source='kepco',kind='keyword',value='지하시설물',name='지하시설물')
        underground = CollectionRule.objects.create(source='kepco',kind='industry',value='지하시설물측량업',name='지하시설물측량업')
        digital_map = CollectionRule.objects.create(source='kepco',kind='industry',value='수치지도제작업',name='수치지도제작업')
        for rule in (self.kepco, underground, digital_map, keyword):
            bind_rule(rule)
            self.assertTrue(rule_matches(rule, row, details))
            store_notice(row, details, rule, self.now)
        self.assertEqual(Notice.objects.filter(source='kepco',number='E012607882').count(),1)
        self.assertEqual(Notice.objects.get(number='E012607882').rules.count(),4)
        with patch('procurement.preferences.stored_ids',return_value=[str(self.g2b.pk)]), \
             patch('procurement.tenant.review_rows',return_value={}), patch('procurement.tenant.load_filters',return_value={}):
            self.assertEqual(list_notices('company_a')[0]['bid_notice_no'],'E012607882')

    def test_central_status_groups_source_rows_under_one_industry(self):
        from django.template.loader import render_to_string
        from .dashboard import snapshot
        data = snapshot()
        self.assertEqual(len(data['condition_groups']), 1)
        self.assertEqual(len(data['condition_groups'][0]['rows']), 2)
        html = render_to_string('procurement/central_status.html', data)
        self.assertEqual(html.count('<strong>공공측량업</strong>'), 1)
        self.assertIn('나라장터', html)
        self.assertIn('한국전력', html)
        self.assertNotIn('나라장터 - 공공측량업', html)

    def test_strict_conversion_preserves_unrecognized_and_unmapped_references(self):
        import uuid
        with self.assertRaises(ValueError):
            canonical_ids([str(uuid.uuid4())], strict=True)
        orphan = CollectionRule.objects.create(source='g2b',kind='industry',value='9999',name='사용자 기존 업종',active=False)
        with self.assertRaises(ValueError):
            canonical_ids([str(orphan.pk)],strict=True)
        retained = bind_rule(orphan)
        self.assertFalse(retained.active)
        self.assertEqual(canonical_ids([str(orphan.pk)],strict=True),[str(retained.pk)])


class DiagnosticTests(TransactionTestCase):
    databases = {'default', 'company_a'}

    def test_diagnostic_does_not_claim_api_or_personal_verification_without_evidence(self):
        g2b = CollectionRule.objects.create(kind='industry', value='5023', name='공공측량업')
        kepco = CollectionRule.objects.create(source='kepco',kind='industry',value='공공측량업',name='공공측량업')
        bind_rule(g2b)
        bind_rule(kepco)
        notice = Notice.objects.create(source='kepco',number='E012607882',order='0',title='표본',posted_at=timezone.now(),last_seen_at=timezone.now())
        notice.rules.add(kepco)
        output = StringIO()
        with override_settings(G2B_CENTRAL_TENANT_ALIASES=('company_a',)), \
             patch('procurement.preferences.stored_ids', return_value=[str(g2b.pk)]), \
             patch('procurement.tenant.review_rows', return_value={}), \
             patch('procurement.tenant.load_filters', return_value={}):
            call_command('diagnose_bid_notice_conditions', database='company_a', stdout=output)
        result = json.loads(output.getvalue())
        self.assertIsNone(result['api_received'])
        self.assertTrue(result['central_stored'])
        self.assertEqual(result['title'], notice.title)
        self.assertEqual(result['logical_conditions'], ['public-survey'])
        self.assertTrue(result['interest_match'])
        self.assertTrue(result['candidate_list_visible_open_only'])
        self.assertFalse(result['personal_state_checked'])


class CentralDataMigrationTests(TransactionTestCase):
    def test_existing_rules_activity_notice_links_and_other_industries_survive(self):
        executor = MigrationExecutor(connection)
        executor.migrate([('procurement','0005_remove_collectionrule_procurement_rule_unique_and_more')])
        old = executor.loader.project_state([('procurement','0005_remove_collectionrule_procurement_rule_unique_and_more')]).apps
        Rule = old.get_model('procurement','CollectionRule')
        NoticeOld = old.get_model('procurement','Notice')
        one = Rule.objects.create(source='g2b',kind='industry',value='5023',name='기관 A 이름')
        two = Rule.objects.create(source='kepco',kind='industry',value='공공측량업',name='기관 B 이름')
        disabled = Rule.objects.create(source='g2b',kind='industry',value='1468',name='기존 SW',active=False)
        other = Rule.objects.create(source='g2b',kind='industry',value='9999',name='그 외 업종',active=False)
        kw1 = Rule.objects.create(source='g2b',kind='keyword',value='지하 시설물',name='기존 검색')
        kw2 = Rule.objects.create(source='kepco',kind='keyword',value='지하시설물',name='기관 검색')
        n = NoticeOld.objects.create(number='prior',order='0',title='원본',posted_at=timezone.now(),last_seen_at=timezone.now())
        n.rules.add(one, two)
        try:
            executor = MigrationExecutor(connection)
            executor.migrate([('procurement','0007_bind_logical_conditions')])
            one = CollectionRule.objects.get(pk=one.pk)
            two = CollectionRule.objects.get(pk=two.pk)
            self.assertEqual(one.condition_id,two.condition_id)
            self.assertEqual(canonical_ids([str(one.pk),str(two.pk)],strict=True),[str(one.condition_id)])
            self.assertFalse(CollectionRule.objects.get(pk=disabled.pk).active)
            self.assertFalse(CollectionRule.objects.get(pk=other.pk).active)
            self.assertEqual(Notice.objects.get(pk=n.pk).rules.count(),2)
            self.assertEqual(CollectionRule.objects.count(),6)
            self.assertEqual(CollectionRule.objects.get(pk=kw1.pk).condition_id, CollectionRule.objects.get(pk=kw2.pk).condition_id)
        finally:
            MigrationExecutor(connection).migrate([('procurement','0007_bind_logical_conditions')])


@override_settings(G2B_CENTRAL_TENANT_ALIASES=('company_a','company_b'))
class TenantConversionTests(TestCase):
    databases = {'default','company_a','company_b'}

    @classmethod
    def setUpTestData(cls):
        for alias in ('company_a','company_b'):
            with connections[alias].cursor() as cur:
                if connections[alias].vendor == 'postgresql':
                    cur.execute('CREATE SCHEMA IF NOT EXISTS bid')
                    cur.execute(importlib.import_module('geoflow_ops.migrations.0038_bid_central_preferences').SQL)
                else:
                    cur.execute('PRAGMA database_list')
                    if 'bid' not in {row[1] for row in cur.fetchall()}:
                        cur.execute("ATTACH DATABASE ':memory:' AS bid")
                    cur.execute('CREATE TABLE bid.central_preferences (id integer PRIMARY KEY, rule_ids text)')

    def setUp(self):
        self.rule = CollectionRule.objects.create(source='g2b',kind='industry',value='5031',name='지하시설물측량업')
        self.condition = bind_rule(self.rule)
        for alias in ('company_a','company_b'):
            with connections[alias].cursor() as cur:
                cur.execute('INSERT INTO bid.central_preferences(id,rule_ids) VALUES(1,%s)',[json.dumps([str(self.rule.pk)])])

    def test_save_accepts_only_logical_ids_and_preserves_other_tenant(self):
        with self.assertRaises(ValueError):
            save('company_a',[str(self.rule.pk)])
        if connections['company_a'].vendor != 'postgresql':
            self.skipTest('PostgreSQL JSONB write contract')
        save('company_a',[str(self.condition.pk)])
        self.assertEqual(selected_conditions('company_a'),[str(self.condition.pk)])
        self.assertEqual(selected_ids('company_b'),[str(self.rule.pk)])
        save('company_a',[])
        self.assertEqual(selected_conditions('company_a'),[])

    def test_backup_dry_run_apply_retry_and_guarded_restore(self):
        if connections['company_a'].vendor != 'postgresql':
            self.skipTest('PostgreSQL preference conversion')
        with TemporaryDirectory() as directory:
            backup = Path(directory)/'before.json'
            out = StringIO()
            call_command('migrate_bid_interest_conditions',database='company_a',stdout=out)
            self.assertFalse(backup.exists())
            self.assertIn('applied=False',out.getvalue())
            call_command('migrate_bid_interest_conditions',database='company_a',execute=True,backup_file=str(backup),stdout=StringIO())
            stored = json.loads(backup.read_text())
            self.assertEqual(stored['before'],[str(self.rule.pk)])
            self.assertEqual(stored['after'],[str(self.condition.pk)])
            call_command('migrate_bid_interest_conditions',database='company_a',execute=True,backup_file=str(backup),stdout=StringIO())
            self.assertEqual(json.loads(backup.read_text()),stored)
            self.assertEqual(selected_ids('company_b'),[str(self.rule.pk)])
            call_command('migrate_bid_interest_conditions',database='company_a',execute=True,
                         restore_file=str(backup),backup_file=str(Path(directory)/'undo.json'),stdout=StringIO())
            with connections['company_a'].cursor() as cur:
                cur.execute('SELECT rule_ids FROM bid.central_preferences WHERE id=1')
                raw = cur.fetchone()[0]
                self.assertEqual(json.loads(raw) if isinstance(raw, str) else raw, [str(self.rule.pk)])
            save('company_a',[])
            with self.assertRaises(CommandError):
                call_command('migrate_bid_interest_conditions',database='company_a',execute=True,
                             restore_file=str(backup),backup_file=str(Path(directory)/'fail.json'),stdout=StringIO())

    def test_no_row_and_explicit_empty_keep_original_meanings(self):
        if connections['company_a'].vendor != 'postgresql':
            self.skipTest('PostgreSQL preferences migration')
        with connections['company_a'].cursor() as cur:
            cur.execute('DELETE FROM bid.central_preferences')
        out = StringIO()
        call_command('migrate_bid_interest_conditions',database='company_a',execute=True,stdout=out)
        self.assertIn('preferences=absent',out.getvalue())
        with patch('procurement.preferences.load_filters',return_value={'industry':[{'code':'5031'}]}):
            self.assertEqual(selected_conditions('company_a'),[str(self.condition.pk)])
            save('company_a',[])
        with patch('procurement.preferences.load_filters',return_value={'industry':[{'code':'5031'}]}):
            self.assertEqual(selected_conditions('company_a'),[])
