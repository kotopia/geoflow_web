from datetime import date, datetime, timedelta
from unittest.mock import patch
from django.test import TestCase
from .tests import NOW, ROW, DETAILS, FakeClient
from . import tests as base_tests
from .models import CollectionPeriod, CollectionRule, CollectionJob, CollectionWindow, Notice
from .period import selection, months_before, bounds
from .service import enqueue_rule, run_step, store_notice
from .policy import minute, retention_start
from .views_central import PeriodForm, dashboard
from geoflow_ops.bids.client import G2BError


class PeriodCollectionTests(TestCase):
    def setUp(self):
        self.rule = CollectionRule.objects.create(kind='keyword', value='GIS', name='GIS')
        self.job = enqueue_rule(self.rule, NOW)
        self.client = FakeClient()
        self.client.search = lambda *a: []

    def test_default_month_stops_without_deleting_or_claiming_two_year_completion(self):
        store_notice(ROW, DETAILS, self.rule, NOW)
        scope = selection(NOW)
        self.assertEqual(scope['start_date'], date(2026, 8, 11))
        self.assertFalse(CollectionPeriod.objects.exists())
        for _ in range(40):
            self.job.refresh_from_db()
            if not run_step(self.job, self.client, NOW, mode='backfill'):
                break
        else:
            self.fail('Backfill did not stop at selected boundary')
        self.job.refresh_from_db()
        self.assertEqual(self.job.backfill_status, 'RANGE_COMPLETE')
        self.assertEqual(Notice.objects.count(), 1)
        self.assertFalse(CollectionWindow.objects.filter(start__lt=scope['start']).exists())
        self.assertEqual(CollectionWindow.objects.order_by('start').first().start, scope['start'])

    def test_custom_end_is_inclusive_korean_date_and_clamped_to_today(self):
        CollectionPeriod.objects.create(start_date=date(2026,8,1), end_date=date(2026,8,5))
        lower, upper = bounds(self.job, NOW)
        self.assertEqual(lower.isoformat(), '2026-08-01T00:00:00+09:00')
        self.assertEqual(upper.isoformat(), '2026-08-05T23:59:00+09:00')
        run_step(self.job, self.client, NOW, mode='backfill')
        self.assertEqual(CollectionWindow.objects.get().end, upper)

    def test_out_of_scope_checkpoint_is_preserved_and_restored_after_expansion(self):
        start = self.job.backfill_start + timedelta(days=20)
        checkpoint = dict(mode='backfill', start=start.isoformat(), end=(start+timedelta(days=1)).isoformat(),
                          checkpoint_version=1, api_page_cache={}, processed=0)
        self.job.backfill_progress = checkpoint
        self.job.save()
        run_step(self.job, self.client, NOW, mode='backfill')
        self.job.refresh_from_db()
        self.assertEqual(self.job.backfill_progress['suspended_windows'], [checkpoint])
        CollectionPeriod.objects.create(start_date=self.job.backfill_start.date(), end_date=minute(NOW).date())
        run_step(self.job, self.client, NOW, mode='backfill')
        self.job.refresh_from_db()
        self.assertEqual(datetime.fromisoformat(self.job.backfill_progress['start']), start)
        self.assertEqual(self.job.backfill_progress['suspended_windows'], [])
        self.assertEqual(CollectionWindow.objects.count(), 2)

    def test_scope_change_during_request_pauses_without_advancing_window(self):
        def search(*a):
            CollectionPeriod.objects.create(start_date=date(2026,9,1), end_date=date(2026,9,2))
            return []
        self.client.search = search
        with self.assertRaises(G2BError) as caught:
            run_step(self.job, self.client, NOW, mode='backfill')
        self.assertEqual(caught.exception.code, 'SCOPE_CHANGED')
        self.assertFalse(CollectionWindow.objects.exists())
        self.job.refresh_from_db()
        self.assertEqual(self.job.backfill_status, 'PAUSED')
        self.assertFalse(self.job.backfill_progress.get('finished', False))

    def test_live_collection_continues_when_historical_scope_is_complete(self):
        CollectionPeriod.objects.create(start_date=date(2026,8,1), end_date=date(2026,8,2))
        for _ in range(4):
            self.job.refresh_from_db()
            run_step(self.job, self.client, NOW, mode='backfill')
        self.job.refresh_from_db()
        self.assertEqual(self.job.backfill_status, 'RANGE_COMPLETE')
        self.assertTrue(run_step(self.job, self.client, NOW, mode='live'))
        self.job.refresh_from_db()
        self.assertEqual(self.job.last_incremental_success, minute(NOW))

    def test_calendar_presets_and_server_validation(self):
        self.assertEqual(months_before(date(2024,3,31),1), date(2024,2,29))
        with patch('procurement.period.timezone.now', return_value=NOW):
            form=PeriodForm({'preset':'3'})
            self.assertTrue(form.is_valid(), form.errors)
            self.assertEqual(form.cleaned_data['start_date'], date(2026,6,11))
            for data in ({'start_date':'2023-01-01','end_date':'2026-09-11'},
                         {'start_date':'2026-09-10','end_date':'2026-09-12'},
                         {'start_date':'2026-09-10','end_date':'2026-09-09'},
                         {'preset':'999'}):
                self.assertFalse(PeriodForm(data).is_valid())


class PeriodViewTests(TestCase):
    setUpTestData = classmethod(base_tests.CentralDashboardTests.setUpTestData.__func__)
    request = base_tests.CentralDashboardTests.request

    def test_period_save_requires_central_admin_and_csrf_and_no_api(self):
        data={'action':'set_period','preset':'1'}
        with patch('control.decorators.lookup_user_id_from_request', return_value='tenant-admin'):
            self.assertEqual(dashboard(self.request('post',data)).status_code,403)
        with patch('control.decorators.lookup_user_id_from_request', return_value='central-admin'), \
             patch('procurement.client.urlopen') as api:
            self.assertEqual(dashboard(self.request('post',data,csrf=False)).status_code,403)
            self.assertFalse(CollectionPeriod.objects.exists())
            self.assertEqual(dashboard(self.request('post',data)).status_code,302)
            self.assertEqual(CollectionPeriod.objects.count(),1)
            self.assertEqual(dashboard(self.request()).status_code,200)
            api.assert_not_called()

    def test_invalid_range_is_rejected_without_changing_saved_period(self):
        saved=CollectionPeriod.objects.create(start_date=date(2026,8,1),end_date=date(2026,8,31))
        with patch('control.decorators.lookup_user_id_from_request',return_value='central-admin'):
            response=dashboard(self.request('post',{'action':'set_period','start_date':'2026-09-11','end_date':'2026-08-01'}))
        self.assertEqual(response.status_code,200)
        saved.refresh_from_db()
        self.assertEqual(saved.start_date,date(2026,8,1))
