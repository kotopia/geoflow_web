from datetime import timedelta
from unittest.mock import Mock, patch
from django.test import TestCase
from .tests import ROW, DETAILS, NOW, FakeClient
from .models import CollectionRule, CollectionJob, CollectionWindow, Notice
from .service import enqueue_rule, run_step, store_notice
from .lifecycle import match_existing, reactivate, coverage_gap
from .policy import minute, retention_start
from geoflow_ops.bids.client import G2BError


class LifecycleTests(TestCase):
    def setUp(self):
        self.rule = CollectionRule.objects.create(kind="keyword", value="GIS", name="GIS")
        self.job = enqueue_rule(self.rule, NOW)

    def test_stale_local_match_cannot_overwrite_reactivated_generation(self):
        store_notice(ROW, DETAILS, self.rule, NOW)
        reactivate(self.rule, NOW + timedelta(days=1))
        self.assertFalse(match_existing(self.job, minute(NOW)))
        self.job.refresh_from_db()
        self.assertEqual(self.job.local_matched, 0)
        self.assertIsNone(self.job.local_match_cursor)
        self.assertFalse(self.job.local_match_complete)

    def test_physical_prune_is_blocked_until_business_references_are_protected(self):
        from django.core.management import call_command, CommandError
        store_notice(ROW, DETAILS, self.rule, NOW)
        with self.assertRaises(CommandError):
            call_command("prune_central_bids", execute=True)
        self.assertEqual(Notice.objects.count(), 1)

    def test_new_rule_targets_two_years_and_reuses_existing_source(self):
        store_notice(ROW, DETAILS, self.rule, NOW)
        other = CollectionRule.objects.create(kind="keyword", value="DB", name="DB")
        job = enqueue_rule(other, NOW)
        self.assertEqual(job.backfill_start, retention_start(minute(NOW)))
        self.assertEqual(job.backfill_end, minute(NOW))
        self.assertTrue(match_existing(job, minute(NOW)))
        self.assertEqual(Notice.objects.count(), 1)
        self.assertEqual(Notice.objects.get().rules.count(), 2)
        self.assertEqual(job.local_matched, 1)
        client = FakeClient()
        client.details = Mock(side_effect=AssertionError("duplicate details"))
        run_step(job, client, NOW)
        self.assertEqual(Notice.objects.count(), 1)

    def test_backfill_checkpoint_survives_interleaved_incremental(self):
        first = dict(ROW, bidNtceNo="first")
        second = dict(ROW, bidNtceNo="second")
        client = FakeClient()
        client.search = lambda *a: [first, second]
        client.details = Mock(side_effect=[DETAILS, G2BError("BUDGET_EXHAUSTED", "pause")])
        with self.assertRaises(G2BError):
            run_step(self.job, client, NOW, mode="backfill")
        self.job.refresh_from_db()
        checkpoint = self.job.backfill_progress.copy()
        run_step(self.job, FakeClient(), NOW + timedelta(minutes=5), mode="live")
        self.job.refresh_from_db()
        self.assertEqual(self.job.backfill_progress, checkpoint)
        client.details = Mock(return_value=DETAILS)
        run_step(self.job, client, NOW + timedelta(minutes=10), mode="backfill")
        self.assertEqual(client.details.call_count, 1)
        self.assertEqual(client.details.call_args.args[0]["bidNtceNo"], "second")
        self.job.refresh_from_db()
        self.assertTrue(self.job.backfill_progress["finished"])
        self.assertIsNotNone(self.job.last_incremental_success)

    def test_disabled_rule_pauses_and_reactivation_preserves_source(self):
        store_notice(ROW, DETAILS, self.rule, NOW)
        old_id = Notice.objects.get().pk
        old_generation = self.job.generation
        self.rule.active = False
        self.rule.save()
        client = Mock()
        self.assertFalse(run_step(self.job, client, NOW))
        client.search.assert_not_called()
        self.rule.active = True
        self.rule.save()
        reactivate(self.rule, NOW + timedelta(days=1))
        self.job.refresh_from_db()
        self.assertNotEqual(self.job.generation, old_generation)
        self.assertEqual(self.job.backfill_start, retention_start(minute(NOW + timedelta(days=1))))
        self.assertEqual(Notice.objects.get().pk, old_id)
        self.assertEqual(self.job.backfill_status, "BACKFILL_PENDING")

    def test_cursor_at_end_without_receipts_is_not_complete(self):
        self.job.backfill_start = minute(NOW) - timedelta(days=1)
        self.job.backfill_cursor = self.job.backfill_end
        self.job.save()
        self.assertIsNotNone(coverage_gap(self.job, minute(NOW)))
        client = FakeClient()
        client.search = lambda *a: []
        run_step(self.job, client, NOW, mode="backfill")
        self.job.refresh_from_db()
        self.assertEqual(self.job.backfill_status, "BACKFILL_COMPLETE")
        self.assertIsNone(coverage_gap(self.job, minute(NOW)))

    def test_missing_database_match_cannot_advance_cursor(self):
        before = self.job.backfill_cursor
        with patch("procurement.service.store_notice", return_value="inserted"):
            with self.assertRaises(G2BError) as caught:
                run_step(self.job, FakeClient(), NOW, mode="backfill")
        self.assertEqual(caught.exception.code, "MATCH_COUNT_MISMATCH")
        self.job.refresh_from_db()
        self.assertEqual(self.job.backfill_cursor, before)
        self.assertFalse(CollectionWindow.objects.exists())

    def test_changed_condition_is_separate_job_and_source_is_shared(self):
        store_notice(ROW, DETAILS, self.rule, NOW)
        other = CollectionRule.objects.create(kind="keyword", value="GIS DB", name="GIS DB")
        job = enqueue_rule(other, NOW + timedelta(days=1))
        self.assertNotEqual(job.pk, self.job.pk)
        self.assertEqual(job.backfill_status, "BACKFILL_PENDING")
        match_existing(job, minute(NOW + timedelta(days=1)))
        self.assertEqual(Notice.objects.count(), 1)

    def test_daily_insert_update_counts_do_not_count_unchanged_upsert(self):
        from .models import ApiBudget
        store_notice(ROW, DETAILS, self.rule, NOW)
        store_notice(ROW, DETAILS, self.rule, NOW)
        store_notice(dict(ROW, bidNtceNm="GIS 수정"), DETAILS, self.rule, NOW)
        budget = ApiBudget.objects.get(day=minute(NOW).date())
        self.assertEqual((budget.inserted, budget.updated), (1, 1))
