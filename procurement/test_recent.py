from contextlib import nullcontext
from datetime import datetime, timedelta
from unittest.mock import patch
from django.test import TestCase, SimpleTestCase, override_settings
from .tests import NOW, FakeClient
from .models import CollectionRule, CollectionWindow, CollectionJob, CollectionPeriod
from .service import enqueue_rule, run_step, run_worker
from .lifecycle import recent_backfill_window
from .client import Client
from .policy import minute
from geoflow_ops.bids.client import G2BError


class RecentBackfillTests(TestCase):
    def setUp(self):
        self.rule = CollectionRule.objects.create(kind='keyword', value='GIS', name='GIS')
        self.job = enqueue_rule(self.rule, NOW)
        CollectionPeriod.objects.create(start_date=self.job.backfill_start.date(), end_date=minute(NOW).date())

    def test_newest_days_first_and_restart_uses_receipts(self):
        for days in range(3):
            job = CollectionJob.objects.get(pk=self.job.pk)
            client = FakeClient()
            client.search = lambda *a: []
            run_step(job, client, NOW, mode='backfill')
            job.refresh_from_db()
            self.assertEqual(datetime.fromisoformat(job.backfill_progress['end']), minute(NOW)-timedelta(days=days))
            self.assertEqual(datetime.fromisoformat(job.backfill_progress['start']), minute(NOW)-timedelta(days=days+1))
        self.assertEqual(CollectionWindow.objects.count(), 3)

    def test_verified_recent_interval_is_skipped_even_with_old_cursor(self):
        CollectionWindow.objects.create(job=self.job, generation=self.job.generation, mode='backfill',
            start=minute(NOW)-timedelta(days=7), end=minute(NOW), metrics={}, verified=True, completed_at=NOW)
        start, end = recent_backfill_window(self.job, NOW)
        self.assertEqual(end, minute(NOW)-timedelta(days=7))
        self.assertEqual(start, minute(NOW)-timedelta(days=8))

    def test_incomplete_legacy_window_is_finished_before_switching_direction(self):
        start = self.job.backfill_start + timedelta(days=20)
        self.job.backfill_progress = dict(mode='backfill', start=start.isoformat(),
            end=(start+timedelta(days=1)).isoformat(), checkpoint_version=1)
        self.job.save()
        client = FakeClient()
        calls = []
        client.search = lambda rule, a, b: calls.append((a,b)) or []
        run_step(self.job, client, NOW, mode='backfill')
        self.assertEqual(calls[0][0], start)
        self.job.refresh_from_db()
        run_step(self.job, client, NOW, mode='backfill')
        self.assertEqual(calls[1][1], minute(NOW))

    def test_gap_near_retention_boundary_does_not_cross_cutoff(self):
        lower = self.job.backfill_start
        CollectionWindow.objects.create(job=self.job, generation=self.job.generation, mode='backfill',
            start=lower+timedelta(hours=2), end=self.job.backfill_end, metrics={}, verified=True, completed_at=NOW)
        self.assertEqual(recent_backfill_window(self.job, NOW), (lower, lower+timedelta(hours=2)))

    def test_budget_heavy_rule_does_not_starve_other_active_rules(self):
        other = CollectionRule.objects.create(kind='keyword', value='측량', name='측량')
        enqueue_rule(other, NOW)
        visited = []
        def step(job, client, now=None, mode=None):
            visited.append((job.rule_id, mode))
            client.budget = 0
            raise G2BError('BUDGET_EXHAUSTED', 'pause')
        with patch('procurement.service.worker_lock', return_value=nullcontext(True)), \
             patch('procurement.service.run_step', side_effect=step):
            run_worker(budget=40, max_steps=2)
        self.assertEqual({r for r,m in visited if m == 'live'}, {self.rule.pk, other.pk})
        self.assertEqual({r for r,m in visited if m == 'backfill'}, {self.rule.pk, other.pk})


class PacingTests(SimpleTestCase):
    @override_settings(G2B_REQUEST_INTERVAL_SECONDS=1)
    def test_calls_are_spaced_without_consuming_budget(self):
        client = Client()
        with patch('procurement.client.time.monotonic', side_effect=[10, 10, 10.2, 11]), \
             patch('procurement.client.time.sleep') as sleep:
            client.pace()
            client.pace()
        sleep.assert_called_once()
        self.assertAlmostEqual(sleep.call_args.args[0], .8)
        self.assertEqual(client.budget, 100)

    def test_deadline_stops_before_network_or_reserving_request(self):
        client = Client()
        client.deadline = 120
        with patch('procurement.client.time.monotonic', return_value=100):
            with self.assertRaises(G2BError) as caught:
                client.pace()
        self.assertEqual(caught.exception.code, 'TIME_BUDGET_EXHAUSTED')
