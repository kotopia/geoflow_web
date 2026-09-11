from datetime import datetime, timedelta, timezone as tz
from unittest.mock import patch

from django.test import TestCase, SimpleTestCase, override_settings
from django.db import connections

from geoflow_ops.bids.client import G2BError
from .models import CollectionRule, CollectionJob, Notice, NoticeRevision, ApiBudget
from .policy import retention_start, minute, canonical_order
from .service import enqueue_rule, run_step, store_notice, enabled, central_alias
from .client import Client

NOW = datetime(2026, 9, 11, 3, 0, tzinfo=tz.utc)
ROW = dict(bidNtceNo="test-001", bidNtceOrd="000", bidNtceNm="GIS DB 구축",
           bidNtceDt="2026-09-10 09:00:00", bidClseDt="2026-10-01 10:00:00",
           bidNtceDtlUrl="https://www.g2b.go.kr/test")
DETAILS = {"regions": [], "industries": [], "products": []}


class PolicyTests(SimpleTestCase):
    def test_korean_api_clock_and_leap_year(self):
        self.assertEqual(minute(NOW).hour, 12)
        self.assertEqual(retention_start(datetime(2024, 2, 29, tzinfo=tz.utc)).day, 28)
        self.assertEqual(canonical_order("000"), canonical_order("00"))

    def test_missing_tenant_fails_closed(self):
        for alias in (None, "", "default"):
            with self.assertRaises(ValueError):
                enabled(alias)
        self.assertFalse(enabled("company_a"))


class FakeClient:
    def search(self, *args):
        return [ROW]

    def changes(self, *args):
        return []

    def details(self, row):
        return DETAILS


class CollectionTests(TestCase):
    def setUp(self):
        self.rule = CollectionRule.objects.create(kind="keyword", value="GIS", name="GIS")
        self.job = enqueue_rule(self.rule, NOW)

    def test_enqueue_is_idempotent_and_two_years(self):
        enqueue_rule(self.rule, NOW)
        self.assertEqual(CollectionJob.objects.count(), 1)
        self.assertEqual(self.job.backfill_cursor.year, 2024)

    def test_duplicates_and_revision_history(self):
        store_notice(ROW, DETAILS, self.rule, NOW)
        store_notice(dict(ROW, bidNtceOrd="00"), DETAILS, self.rule, NOW)
        self.assertEqual(Notice.objects.count(), 1)
        store_notice(dict(ROW, bidNtceNm="GIS DB 구축 변경"), DETAILS, self.rule, NOW)
        self.assertEqual(Notice.objects.count(), 1)
        self.assertEqual(NoticeRevision.objects.count(), 3)

    def test_empty_details_stay_unknown(self):
        store_notice(ROW, DETAILS, self.rule, NOW)
        notice = Notice.objects.get()
        self.assertFalse(notice.region_known)
        self.assertFalse(notice.industry_known)
        self.assertNotIn("전국", notice.region_text)

    def test_failure_does_not_advance_any_cursor(self):
        with patch.object(FakeClient, "details", side_effect=G2BError("HTTP_400", "bad")):
            with self.assertRaises(G2BError):
                run_step(self.job, FakeClient(), NOW)
        self.job.refresh_from_db()
        self.assertEqual(self.job.status, "failed")
        self.assertEqual(self.job.live_cursor, minute(NOW))
        self.assertEqual(self.job.backfill_cursor, retention_start(minute(NOW)))
        self.assertIsNone(self.job.last_success_at)

    def test_backfill_and_live_checkpoints_independent(self):
        run_step(self.job, FakeClient(), NOW)
        self.job.refresh_from_db()
        initial_live = self.job.live_cursor
        run_step(self.job, FakeClient(), NOW)
        self.job.refresh_from_db()
        self.assertEqual(self.job.live_cursor, initial_live)
        self.assertEqual(self.job.backfill_cursor, retention_start(minute(NOW)) + timedelta(days=1))

    def test_changed_old_notice_updates_despite_not_in_posting_search(self):
        store_notice(ROW, DETAILS, self.rule, NOW)
        client = FakeClient()
        client.search = lambda *a: []
        client.changes = lambda *a: [dict(ROW, bidNtceNm="취소공고")]
        run_step(self.job, client, NOW)
        self.assertEqual(Notice.objects.get().title, "취소공고")

    def test_no_unrelated_changes_persisted(self):
        client = FakeClient()
        client.search = lambda *a: []
        client.changes = lambda *a: [dict(ROW, bidNtceNm="급식 물품")]
        run_step(self.job, client, NOW)
        self.assertFalse(Notice.objects.exists())

    @override_settings(G2B_CENTRAL_DAILY_BUDGET=1)
    def test_shared_budget(self):
        Client().reserve()
        with self.assertRaises(G2BError):
            Client().reserve()
        self.assertEqual(ApiBudget.objects.get().used, 1)

    def test_same_source_reuses_auxiliary_data(self):
        store_notice(ROW, DETAILS, self.rule, NOW)
        with patch.object(FakeClient, "details", side_effect=AssertionError("duplicate external call")):
            run_step(self.job, FakeClient(), NOW)

    def test_missing_date_fails_instead_of_false_complete(self):
        with self.assertRaises(G2BError):
            store_notice(dict(ROW, bidNtceDt=""), DETAILS, self.rule, NOW)


class TenantIsolationTests(TestCase):
    databases = {"default", "company_a", "company_b"}

    @classmethod
    def setUpTestData(cls):
        import importlib
        for alias in ("company_a", "company_b"):
            conn = connections[alias]
            with conn.cursor() as cur:
                if conn.vendor == "postgresql":
                    cur.execute("CREATE SCHEMA IF NOT EXISTS bid")
                    cur.execute(importlib.import_module("geoflow_ops.migrations.0037_central_bid_reviews").SQL)
                else:
                    cur.execute("ATTACH DATABASE ':memory:' AS bid")
                    cur.execute("CREATE TABLE bid.central_reviews (central_notice_id text PRIMARY KEY, status text, memo text)")

    def setUp(self):
        self.rule = CollectionRule.objects.create(kind="keyword", value="GIS", name="GIS")
        store_notice(ROW, DETAILS, self.rule, datetime.now(tz.utc))
        self.notice = Notice.objects.get()
        for alias, status in (("company_a", "interested"), ("company_b", "excluded")):
            with connections[alias].cursor() as cur:
                if connections[alias].vendor == "postgresql":
                    cur.execute("""INSERT INTO bid.central_reviews
                      (central_notice_id,notice_number,notice_order,title,status,memo)
                      VALUES (%s,%s,%s,%s,%s,%s)""",
                      [str(self.notice.pk), self.notice.number, self.notice.order, self.notice.title, status, alias])
                else:
                    cur.execute("INSERT INTO bid.central_reviews VALUES (%s,%s,%s)", [str(self.notice.pk), status, alias])

    def test_company_state_filters_before_count_and_page(self):
        from .tenant import count_notices, list_notices
        self.assertEqual(count_notices("company_a", include_all=True), 1)
        self.assertEqual(count_notices("company_b", include_all=True), 0)
        rows = list_notices("company_b", include_all=True, review_status="excluded")
        self.assertEqual(rows[0]["memo"], "company_b")
        self.assertEqual(list_notices("company_a", include_all=True)[0]["memo"], "company_a")

    def test_unknown_does_not_hide_candidate_and_keyword_boundary(self):
        from .tenant import count_notices
        with patch("procurement.tenant.load_filters", return_value={"include": [{"keyword": "GIS"}]}):
            self.assertEqual(count_notices("company_a"), 1)
            Notice.objects.update(title="GIST 프로그램")
            self.assertEqual(count_notices("company_a"), 0)
