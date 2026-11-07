from datetime import timedelta
from unittest.mock import patch, MagicMock
from io import BytesIO
import json
from urllib.error import HTTPError
from django.test import TestCase, override_settings
from django.utils import timezone
from geoflow_ops.bids.client import G2BError
from .models import CollectionRule, Notice, CollectionJob
from .kepco import KepcoClient, adapt, industry_matches
from .service import enqueue_rule, run_step, store_notice
from .tenant import query_notices
from .policy import notice_id


def row(**changes):
    return dict(companyId='COM01', itemType='Service', no='shared-number', name='공간정보 구축',
                noticeDate=timezone.localdate().strftime('%Y%m%d'),
                endDatetime=(timezone.now()+timedelta(days=5)).astimezone().strftime('%Y-%m-%d %H:%M:%S'),
                bidAttendRestrict='공공 측량업 등록 업체', **changes)


@override_settings(KEPCO_API_KEY='fixture-key', G2B_REQUEST_INTERVAL_SECONDS=0)
class KepcoTests(TestCase):
    def setUp(self):
        self.rule = CollectionRule.objects.create(source='kepco', kind='industry', value='공공측량업', name='공공측량업')
        self.now = timezone.now().replace(second=0, microsecond=0)

    def test_source_identity_and_candidate_match(self):
        item = adapt(row(estimatedPriceBasicAmount='1234567'))
        self.assertTrue(industry_matches(self.rule.value, item['_kepco']))
        self.assertFalse(industry_matches('5023', item['_kepco']))
        self.assertFalse(industry_matches('<br>', item['_kepco']))
        self.assertFalse(industry_matches('지하시설물측량업', item['_kepco']))
        self.assertIsNone(adapt(dict(row(), itemType='Construction')))
        g2b = CollectionRule.objects.create(kind='industry', value='5023', name='공공측량업')
        details = {'regions': [], 'industries': [], 'products': []}
        store_notice(item, details, self.rule, self.now)
        store_notice(item, details, g2b, self.now)
        self.assertEqual(Notice.objects.count(), 2)
        self.assertEqual(Notice.objects.get(source='g2b').pk, notice_id('shared-number','0'))
        self.assertNotEqual(Notice.objects.get(source='kepco').pk, notice_id('shared-number','0'))
        self.assertFalse(Notice.objects.get(source='kepco').region_known)
        self.assertEqual(Notice.objects.get(source='kepco').summary["basic_amount"], "1234567")
        store_notice(item, details, self.rule, self.now)
        self.assertEqual(Notice.objects.count(), 2)

    def test_post_secret_not_in_url_and_shape_validation(self):
        opener = MagicMock()
        opener.open.return_value.__enter__.return_value = BytesIO(json.dumps({'data':[row()]}).encode())
        with patch('procurement.kepco.build_opener', return_value=opener):
            client=KepcoClient()
            self.assertEqual(len(client.day('20261102')), 1)
            req=opener.open.call_args.args[0]
            self.assertNotIn('fixture-key', req.full_url)
            self.assertEqual(req.method,'POST')
            self.assertIn(b'apiKey=fixture-key',req.data)
            self.assertEqual(len(client.day('20261102')),1)
            self.assertEqual(opener.open.call_count,1)
        opener.open.return_value.__enter__.return_value = BytesIO(b'{"error":"do not store"}')
        with patch('procurement.kepco.build_opener', return_value=opener), self.assertRaises(G2BError):
            KepcoClient().day('20261102')

    def test_failure_does_not_advance_and_resume_reuses_daily_checkpoint(self):
        job=enqueue_rule(self.rule,self.now)
        client=KepcoClient()
        calls=[]
        def fail(day):
            calls.append(day)
            if len(calls)>1:
                raise G2BError('BUDGET_EXHAUSTED','stop')
            return [row()]
        with patch.object(client,'day',side_effect=fail), self.assertRaises(G2BError):
            run_step(job,client,self.now,mode='backfill')
        job.refresh_from_db()
        self.assertEqual(job.status,'failed')
        self.assertEqual(len(job.backfill_progress['kepco_days']),1)
        saved_day=calls[0]
        retry=KepcoClient()
        with patch.object(retry,'day',return_value=[row()]) as read:
            self.assertTrue(run_step(job,retry,self.now,mode='backfill'))
            self.assertNotIn(saved_day,[c.args[0] for c in read.call_args_list])
        job.refresh_from_db()
        self.assertEqual(job.status,'success')
        self.assertNotIn('kepco_days',job.backfill_progress)
        self.assertEqual(Notice.objects.count(),1)

    def test_http_errors_never_expose_body_or_key(self):
        for code in (401,500):
            opener=MagicMock()
            opener.open.side_effect=HTTPError('secret-url',code,'secret-body',{},None)
            with patch('procurement.kepco.build_opener',return_value=opener), self.assertRaises(G2BError) as error:
                KepcoClient().day('20261102')
            self.assertNotIn('secret',str(error.exception))
        opener.open.side_effect=HTTPError('url',404,'none',{},None)
        with patch('procurement.kepco.build_opener',return_value=opener):
            self.assertEqual(KepcoClient().day('20261102'),[])

    def test_explicit_central_search_optional_filters_and_personal_hide(self):
        notice=Notice.objects.create(source='kepco',number='1',order='0',title='측량',posted_at=self.now,
                                    last_seen_at=self.now,region_known=True,region_text='서울특별시')
        filters={'region':[{'id':'r','name':'충청남도'}], 'include':[{'keyword':'GIS'}], 'exclude':[{'keyword':'측량'}]}
        with patch('procurement.tenant.review_rows',return_value={}), patch('procurement.tenant.load_filters',return_value=filters), patch('procurement.tenant.selected_ids',return_value=[]):
            self.assertEqual(query_notices('company_a',apply_extra=False)[0].count(),0)
            self.assertEqual(query_notices('company_a',include_all=True,apply_extra=False)[0].count(),1)
            self.assertEqual(query_notices('company_a',include_all=True,apply_extra=True)[0].count(),0)
            self.assertEqual(query_notices('company_a',include_all=True,apply_extra=False,sources=['g2b'])[0].count(),0)
            self.assertEqual(query_notices('company_a',include_all=True,apply_extra=False,personal_state={str(notice.pk):{'saved':False,'hidden':True}})[0].count(),0)
        with patch('procurement.tenant.review_rows',return_value={str(notice.pk):{'review_status':'excluded'}}), patch('procurement.tenant.load_filters',return_value={}):
            self.assertEqual(query_notices('company_a',include_all=True)[0].count(),0)
            self.assertEqual(query_notices('company_a',include_all=True,include_excluded=True)[0].count(),1)

    def test_central_industry_form_supports_provider_specific_values(self):
        from .views_central import RuleForm
        from .conditions import bind_rule
        condition = bind_rule(self.rule)
        form=RuleForm({'condition': str(condition.pk), 'source':'kepco','kind':'industry','value':'공공측량업','name':'공공측량업'})
        self.assertTrue(form.is_valid(),form.errors)
        form=RuleForm({'condition': str(condition.pk), 'source':'g2b','kind':'industry','value':'공공측량업','name':'공공측량업'})
        self.assertFalse(form.is_valid())
