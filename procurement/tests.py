from datetime import datetime, timedelta, timezone as tz
from unittest.mock import patch
from io import BytesIO, StringIO
import json
from urllib.error import HTTPError
from urllib.parse import parse_qs, urlparse
from types import SimpleNamespace
from unittest.mock import Mock

from django.test import TestCase, SimpleTestCase, override_settings
from django.db import connections
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import RequestFactory
from django.middleware.csrf import get_token

from geoflow_ops.bids.client import G2BError
from .models import CollectionRule, CollectionJob, Notice, NoticeRevision, ApiBudget
from .policy import retention_start, minute, canonical_order
from .service import enqueue_rule, run_step, store_notice, enabled, central_alias
from .client import Client, SEARCH

NOW = datetime(2026, 9, 11, 3, 0, tzinfo=tz.utc)
ROW = dict(bidNtceNo="test-001", bidNtceOrd="000", bidNtceNm="GIS DB 구축",
           bidNtceDt="2026-09-10 09:00:00", bidClseDt="2026-10-01 10:00:00",
           bidNtceDtlUrl="https://www.g2b.go.kr/test")
DETAILS = {"regions": [], "industries": [], "products": []}


@override_settings(G2B_API_SERVICE_KEY="test%2Bkey%2Fvalue%3D")
class ClientProtocolTests(TestCase):
    def payload(self, total=42, items=None):
        return json.dumps({"response": {"header": {"resultCode": "00"},
                           "body": {"totalCount": total, "items": [ROW] if items is None else items}}}).encode()

    def test_count_uses_single_row_request_and_does_not_store_notices(self):
        output = StringIO()
        with patch("procurement.client.urlopen", return_value=BytesIO(self.payload())) as request:
            call_command("inspect_g2b_bids", start="202609100000", end="202609102359",
                         industry="5031", stdout=output)
        query = parse_qs(urlparse(request.call_args.args[0].full_url).query)
        self.assertEqual(query["serviceKey"], ["test+key/value="])
        self.assertEqual(query["numOfRows"], ["1"])
        self.assertEqual(query["indstrytyCd"], ["5031"])
        self.assertEqual(json.loads(output.getvalue())["totalCount"], 42)
        self.assertEqual(request.call_count, 1)
        self.assertEqual(ApiBudget.objects.get().used, 1)
        self.assertFalse(Notice.objects.exists())
        self.assertFalse(CollectionJob.objects.exists())

    def test_http_gateway_code_retained_without_echoed_secret(self):
        raw = b"<OpenAPI_ServiceResponse><cmmMsgHeader><returnReasonCode>10</returnReasonCode><returnAuthMsg>secret-request-url</returnAuthMsg></cmmMsgHeader></OpenAPI_ServiceResponse>"
        error = HTTPError("https://example.invalid/?serviceKey=secret", 400, "secret", {}, BytesIO(raw))
        with patch("procurement.client.urlopen", side_effect=error):
            with self.assertRaises(G2BError) as caught:
                Client().page(SEARCH)
        self.assertEqual(caught.exception.code, "API_10")
        self.assertNotIn("secret", str(caught.exception))
        self.assertTrue(caught.exception.__suppress_context__)

    def test_json_quota_error_is_distinct_and_sanitized(self):
        raw = b'{"response":{"header":{"resultCode":"22","resultMsg":"secret"}}}'
        with patch("procurement.client.urlopen", return_value=BytesIO(raw)):
            with self.assertRaises(G2BError) as caught:
                Client().page(SEARCH)
        self.assertEqual(caught.exception.code, "API_22")
        self.assertNotIn("secret", str(caught.exception))

    def test_html_error_does_not_become_empty_success(self):
        with patch("procurement.client.urlopen", return_value=BytesIO(b"<html>secret</html>")):
            with self.assertRaises(G2BError) as caught:
                Client().page(SEARCH)
        self.assertEqual(caught.exception.code, "INVALID_RESPONSE")

    def test_invalid_totals_fail_closed(self):
        for total in (None, -1, 1.5, True, "abc"):
            with self.subTest(total=total), patch("procurement.client.urlopen", return_value=BytesIO(self.payload(total))):
                with self.assertRaises(G2BError) as caught:
                    Client().page(SEARCH)
                self.assertEqual(caught.exception.code, "INVALID_TOTAL")

    def test_invalid_diagnostic_options_make_no_request(self):
        with patch("procurement.client.urlopen") as request:
            for options in ({"end": "202609120001"}, {"mode": "changed", "industry": "5031"}):
                args = dict(start="202609100000", end="202609102359")
                args.update(options)
                with self.assertRaises(CommandError):
                    call_command("inspect_g2b_bids", **args)
        request.assert_not_called()

    def test_all_pages_still_collected_and_missing_page_fails(self):
        with patch("procurement.client.urlopen", side_effect=[BytesIO(self.payload(2)), BytesIO(self.payload(2))]):
            self.assertEqual(len(Client().all(SEARCH)), 2)
        with patch("procurement.client.urlopen", side_effect=[BytesIO(self.payload(2)), BytesIO(self.payload(2, []))]):
            with self.assertRaises(G2BError) as caught:
                Client().all(SEARCH)
        self.assertEqual(caught.exception.code, "INCOMPLETE_RESPONSE")


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


class LiveProbeTests(SimpleTestCase):
    def test_probe_checks_seven_endpoints_without_printing_notice_data(self):
        from .live_probe import run_probe
        client = Mock()
        client.page.return_value = SimpleNamespace(total_count=1, items=[ROW])
        lines = []
        self.assertTrue(run_probe(NOW, lines.append, client))
        self.assertEqual(client.page.call_count, 7)
        self.assertNotIn(ROW["bidNtceNo"], "".join(lines))
        first = client.page.call_args_list[0].kwargs
        self.assertEqual(first["inqryBgnDt"], "202609100000")
        self.assertEqual(first["inqryEndDt"], "202609102359")
        self.assertTrue(all(call.kwargs["rows"] == 1 for call in client.page.call_args_list))

    def test_auth_or_quota_failure_stops_further_calls(self):
        from .live_probe import run_probe
        for code in ("API_20", "API_22", "API_23", "MISSING_SERVICE_KEY"):
            client = Mock()
            client.page.side_effect = G2BError(code, "secret-provider-message")
            lines = []
            self.assertFalse(run_probe(NOW, lines.append, client))
            self.assertEqual(client.page.call_count, 1)
            self.assertNotIn("secret-provider-message", "".join(lines))

    def test_no_sample_cannot_be_reported_as_complete_validation(self):
        from .live_probe import run_probe
        client = Mock()
        client.page.return_value = SimpleNamespace(total_count=0, items=[])
        lines = []
        self.assertFalse(run_probe(NOW, lines.append, client))
        self.assertEqual(client.page.call_count, 4)
        self.assertEqual(json.loads(lines[-1])["code"], "NO_SAMPLE")


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

    def test_progress_visible_before_details_finish_and_preserved_on_failure(self):
        def fail(row):
            job = CollectionJob.objects.get(pk=self.job.pk)
            self.assertEqual(job.status, "running")
            self.assertEqual(job.progress["total"], 1)
            self.assertEqual(job.progress["processed"], 0)
            raise G2BError("API_10", "error")
        with patch.object(FakeClient, "details", side_effect=fail):
            with self.assertRaises(G2BError):
                run_step(self.job, FakeClient(), NOW)
        self.job.refresh_from_db()
        self.assertEqual(self.job.progress["total"], 1)
        self.assertEqual(self.job.progress["stored"], 0)

    def test_progress_counts_processed_and_stored_separately(self):
        client = FakeClient()
        client.changes = lambda *args: [dict(ROW, bidNtceNo="unrelated", bidNtceNm="급식")]
        run_step(self.job, client, NOW)
        self.job.refresh_from_db()
        self.assertEqual(self.job.progress["processed"], 2)
        self.assertEqual(self.job.progress["stored"], 1)
        self.assertEqual(self.job.progress["total"], 2)


class CentralDashboardTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        with connections["default"].cursor() as cur:
            cur.execute("CREATE TABLE users (id varchar(40) PRIMARY KEY, is_staff boolean NOT NULL)")
            cur.execute("INSERT INTO users VALUES (%s,%s)", ["central-admin", True])
            cur.execute("INSERT INTO users VALUES (%s,%s)", ["tenant-admin", False])

    def request(self, method="get", data=None, csrf=True):
        factory = RequestFactory()
        if method == "get":
            return factory.get("/control/central/bids/")
        initial = factory.get("/")
        token = get_token(initial)
        request = factory.post("/control/central/bids/", dict(data or {}, csrfmiddlewaretoken=token) if csrf else data)
        request.COOKIES["csrftoken"] = initial.META["CSRF_COOKIE"]
        return request

    def test_authorization_is_checked_for_html_status_and_mutations(self):
        from .views_central import dashboard, status
        for uid in (None, "tenant-admin"):
            with patch("control.decorators.lookup_user_id_from_request", return_value=uid):
                self.assertEqual(dashboard(self.request()).status_code, 403)
                self.assertEqual(status(self.request()).status_code, 403)
                self.assertEqual(dashboard(self.request("post", {"action": "sync_all"})).status_code, 403)
        self.assertFalse(CollectionRule.objects.exists())

    def test_sync_requires_csrf_and_never_calls_external_api(self):
        from .views_central import dashboard
        rule = CollectionRule.objects.create(kind="keyword", value="GIS", name="GIS")
        job = enqueue_rule(rule, NOW)
        with patch("control.decorators.lookup_user_id_from_request", return_value="central-admin"), patch("procurement.client.urlopen") as external:
            self.assertEqual(dashboard(self.request("post", {"action": "sync_all"}, csrf=False)).status_code, 403)
            self.assertEqual(dashboard(self.request("post", {"action": "sync_all"})).status_code, 302)
            self.assertEqual(dashboard(self.request()).status_code, 200)
        external.assert_not_called()
        job.refresh_from_db()
        self.assertTrue(job.requested)
        self.assertEqual(job.backfill_cursor, retention_start(minute(NOW)))

    def test_condition_create_duplicate_and_disable(self):
        from .views_central import dashboard
        data = dict(action="create", kind="industry", value="5031", name="지하시설물측량업")
        with patch("control.decorators.lookup_user_id_from_request", return_value="central-admin"):
            self.assertEqual(dashboard(self.request("post", data)).status_code, 302)
            self.assertEqual(dashboard(self.request("post", data)).status_code, 200)
            rule = CollectionRule.objects.get()
            self.assertEqual(CollectionJob.objects.count(), 1)
            self.assertEqual(dashboard(self.request("post", {"action": "disable", "rule_id": str(rule.pk)})).status_code, 302)
            rule.refresh_from_db()
            self.assertFalse(rule.active)
            self.assertEqual(dashboard(self.request("post", {"action": "sync", "rule_id": "bad"})).status_code, 400)

    def test_unique_total_and_escaped_status_markup(self):
        from .dashboard import snapshot
        from .views_central import status
        one = CollectionRule.objects.create(kind="keyword", value="GIS", name="<script>alert(1)</script>")
        two = CollectionRule.objects.create(kind="industry", value="5031", name="측량")
        store_notice(ROW, DETAILS, one, NOW)
        store_notice(ROW, DETAILS, two, NOW)
        data = snapshot()
        self.assertEqual(data["total"], 1)
        self.assertEqual([row["rule"].stored_count for row in data["rows"]], [1, 1])
        with patch("control.decorators.lookup_user_id_from_request", return_value="central-admin"), patch("procurement.client.urlopen") as external:
            response = status(self.request())
        html = json.loads(response.content)["html"]
        self.assertIn("&lt;script&gt;", html)
        self.assertNotIn("<script>", html)
        external.assert_not_called()


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
