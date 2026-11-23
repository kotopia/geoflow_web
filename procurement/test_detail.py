"""Public notice detail, tenant-owned notes, and safe external attachments."""
import re
import importlib
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from pathlib import Path
from uuid import uuid4

from django.db import connections
from django.http import Http404
from django.template import Context, Engine
from django.test import SimpleTestCase, TestCase, override_settings
from django.utils import timezone

from geoflow_ops.bids import detail
from procurement.models import Notice


class DetailPresentationTests(SimpleTestCase):
    def test_links_allow_official_hosts_without_credentials(self):
        for url in ['javascript:alert(1)', 'https://g2b.go.kr.evil.test/file',
                    'https://user:pass@www.g2b.go.kr/file', 'https://www.g2b.go.kr/file?serviceKey=secret',
                    '//www.g2b.go.kr/file', 'https://[broken']:
            self.assertIsNone(detail.safe_url(url, 'g2b'))
        self.assertEqual(detail.safe_url('https://www.g2b.go.kr/file?id=1', 'g2b'),
                         'https://www.g2b.go.kr/file?id=1')
        self.assertIsNone(detail.safe_url('https://srm.kepco.net/file', 'g2b'))

    def test_all_attachment_slots_nested_and_deduplicated(self):
        url = 'https://www.g2b.go.kr/file?id=10'
        raw = {'notice': {'ntceSpecDocUrl10': url, 'ntceSpecFileNm10': '공고서.hwp'},
               'extra': [{'ntceSpecDocUrl1': url, 'ntceSpecDocUrl2': 'javascript:alert(1)'}]}
        self.assertEqual(detail.attachment_links(raw, {}, 'g2b'), [{'url':url, 'name':'공고서.hwp'}])
        kepco = 'https://srm.kepco.net/file?id=2'
        self.assertEqual(detail.attachment_links({'_kepco':{'filenlink2':kepco,'filename2':'설계.pdf'}},
            {'attachments':[{'url':kepco,'name':'중복'}]}, 'kepco'), [{'url':kepco,'name':'설계.pdf'}])

    def test_all_fields_preserved_and_credentials_removed(self):
        raw = {'notice':{'newField':'<script>alert(1)</script>', 'Service_Key':'secret',
                         'link':'https://www.g2b.go.kr/?token=secret'}, 'regions':[{'code':0}],
               'unknown':False, 'empty':None}
        clean = detail.public_payload(raw)
        values = list(detail.fields(clean))
        self.assertEqual(len(values), 5)
        self.assertNotIn('secret', str(values))
        self.assertIn({'label':'공고 / newField','value':'<script>alert(1)</script>'},values)

    def test_popup_escapes_raw_and_memo_and_preserves_read_only_history(self):
        source = (Path(__file__).resolve().parents[1] /
                  'geoflow_ops/templates/geoflow_ops/bids/notice_detail.html').read_text()
        source = re.sub(r'{% url .*?%}', '/bids/', source)
        engine = Engine(libraries={'humanize':'django.contrib.humanize.templatetags.humanize'})
        n = {'title':'<script>title</script>', 'memo':'</textarea><script>memo</script>',
             'collected_fields':[{'label':'unknown','value':'<img src=x onerror=alert(1)>'}],
             'original_url':'https://www.g2b.go.kr/', 'original_is_search':True}
        html = engine.from_string(source).render(Context({'n':n, 'can_review':True}))
        self.assertNotIn('<script>', html)
        self.assertNotIn('<img ', html)
        self.assertIn('개찰 결과', html)
        self.assertIn('미연동', html)
        self.assertIn('disabled>개찰 결과 보기', html)
        for label in ['공고원문보기','기관 검색','기록 저장','관심 등록','숨기기','수집 정보 전체']:
            self.assertIn(label, html)
        readonly = engine.from_string(source).render(Context({'n':n,'read_only':True,'can_review':False}))
        self.assertNotIn('<form', readonly)
        self.assertIn('&lt;script&gt;memo', readonly)

    def test_schedule_does_not_claim_opening_or_award_completion(self):
        now = datetime(2026, 11, 23, 10, tzinfo=ZoneInfo('Asia/Seoul'))
        for source in ('g2b', 'kepco'):
            n = detail.presentation(dict(source=source, posted_at=now-timedelta(days=1),
                bid_begin_at=now+timedelta(days=1), bid_close_at=now+timedelta(days=2),
                open_at=now+timedelta(days=3)), {}, now=now)
            self.assertEqual(n['schedule_label'], '접수 예정')
            self.assertEqual([e['key'] for e in n['timeline'] if e['elapsed']], ['posted_at'])
            n = detail.presentation(dict(source=source, bid_close_at=now-timedelta(hours=2),
                open_at=now-timedelta(hours=1)), {}, now=now)
            self.assertEqual(n['schedule_label'], '마감')
            self.assertEqual(n['opening_schedule'], '개찰 예정시각 경과')
            self.assertIn('미확인', n['timeline'][-1]['hint'])
            self.assertIn('자동 연동 전', n['result_message'])
            n = detail.presentation(dict(source=source, notice_status='cancelled',
                open_at=now-timedelta(hours=1)), {}, now=now)
            self.assertEqual(n['schedule_label'], '취소')
            self.assertFalse(any(e['elapsed'] for e in n['timeline']))

    def test_g2b_display_uses_raw_registration_and_preserves_zero_and_unknowns(self):
        n = detail.presentation(dict(source='g2b', estimated_price='0', basic_amount='123,456',
            open_at='invalid', bid_begin_at=None), {'notice':{
                'bidQlfctRgstDt':'2026-11-24 18:00', 'sucsfbidMthdNm':'협상에 의한 계약',
                'cmmnSpldmdMethdNm':'공동이행', 'VAT':'0'}})
        values = {field['label']:field['value'] for section in n['sections'] for row in section['rows'] for field in row}
        self.assertEqual(values['추정가격'], '0원')
        self.assertEqual(values['기초금액'], '123,456원')
        self.assertEqual(values['부가가치세'], '0원')
        self.assertEqual(values['사업예산'], '미제공')
        self.assertEqual(values['낙찰방법'], '협상에 의한 계약')
        self.assertEqual(values['공동수급'], '공동이행')
        self.assertIsNone(n['open_at'])
        self.assertEqual(n['registration_close_at'].day, 24)

    def test_kepco_missing_fields_are_not_inferred_from_qualification_or_progress(self):
        n = detail.presentation(dict(source='kepco', qualification_text='충남 소재 공공측량업 등록 업체',
            notice_agency_name='한국전력 충남본부', estimated_price='100000'),
            {'notice':{'_kepco':{'progressstate':'Final'}, 'VAT':'10000', 'cmmnSpldmdMethdNm':'합성값'}})
        values = {field['label']:field['value'] for section in n['sections'] for row in section['rows'] for field in row}
        for key in ('참가가능지역','업종·면허','공동수급','부가가치세','개찰 예정'):
            self.assertEqual(values[key], '미제공')
        self.assertEqual(values['참가자격 원문'], '충남 소재 공공측량업 등록 업체')
        self.assertEqual(n['opening_schedule'], '개찰일 미제공')
        self.assertIn('자동 연동 전', n['result_message'])


@override_settings(G2B_CENTRAL_TENANT_ALIASES=('company_a','company_b'))
class DetailStorageTests(TestCase):
    databases = {'default','company_a','company_b'}

    @classmethod
    def setUpTestData(cls):
        for alias in ('company_a','company_b'):
            with connections[alias].cursor() as cur:
                if connections[alias].vendor == 'postgresql':
                    cur.execute(importlib.import_module('geoflow_ops.migrations.0036_bid_interest_foundation').FORWARD_SQL)
                    cur.execute(importlib.import_module('geoflow_ops.migrations.0037_central_bid_reviews').SQL)
                else:
                    cur.execute('PRAGMA database_list')
                    if 'bid' not in {row[1] for row in cur.fetchall()}:
                        cur.execute("ATTACH DATABASE ':memory:' AS bid")
                    cur.execute('CREATE TABLE bid.central_reviews (central_notice_id text PRIMARY KEY, notice_number text, notice_order text, title text, memo text, status text)')
                    cur.execute('CREATE TABLE bid.notices (id text PRIMARY KEY, title text, raw_payload text, bid_notice_no text, payload_hash text)')
                    cur.execute('CREATE TABLE bid.notice_reviews (notice_id text PRIMARY KEY, memo text, status text)')

    def test_shared_public_detail_has_only_current_tenant_memo(self):
        obj = Notice.objects.create(number='detail',order='000',title='public',
            posted_at=timezone.now(),last_seen_at=timezone.now(),raw={'notice':{'extra':'public data'}})
        for alias in ('company_a','company_b'):
            with connections[alias].cursor() as cur:
                cur.execute('INSERT INTO bid.central_reviews (central_notice_id,notice_number,notice_order,title,memo) VALUES (%s,%s,%s,%s,%s)', [str(obj.pk),obj.number,obj.order,obj.title,alias])
        a,b = detail.load('company_a',obj.pk),detail.load('company_b',obj.pk)
        self.assertEqual(a['collected_fields'],b['collected_fields'])
        self.assertEqual(a['memo'],'company_a')
        self.assertEqual(b['memo'],'company_b')
        self.assertTrue(a['original_is_search'])
        with self.assertRaises(Http404):
            detail.load('company_a',uuid4())
        with self.assertRaises(ValueError):
            detail.load('default',obj.pk)

    def test_history_never_reads_other_tenant_or_central_notice(self):
        pk = uuid4()
        with connections['company_a'].cursor() as cur:
            cur.execute('INSERT INTO bid.notices (id,title,raw_payload,bid_notice_no,payload_hash) VALUES (%s,%s,%s,%s,%s)',
                        [str(pk),'legacy','{"notice":{"bidNtceNm":"legacy"}}','legacy','test-hash'])
            cur.execute('INSERT INTO bid.notice_reviews (notice_id,memo) VALUES (%s,%s)',[str(pk),'history memo'])
        self.assertEqual(detail.load('company_a',str(pk),history=True)['memo'],'history memo')
        with self.assertRaises(Http404):
            detail.load('company_b',str(pk),history=True)
        with self.assertRaises(Http404):
            detail.load('company_a',str(pk))
