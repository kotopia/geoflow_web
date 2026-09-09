import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest import TestCase, mock

from django.core.exceptions import PermissionDenied
from django.test import override_settings

from geoflow_ops.bids.client import (
    BASIS_AMOUNT_OPERATION,
    G2BClient,
    G2BError,
    LICENSE_OPERATION,
    NOTICE_OPERATION,
    REGION_OPERATION,
    parse_response,
)
from geoflow_ops.bids.matcher import evaluate_notice
from geoflow_ops.bids.repository import _json_list
from geoflow_ops.bids import security_views


class Response:
    def __init__(self, payload):
        self.payload = json.dumps(payload).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self):
        return self.payload


class G2BClientTests(TestCase):
    def test_auxiliary_operation_names_match_the_public_api(self):
        self.assertEqual(LICENSE_OPERATION, "getBidPblancListInfoLicenseLimit")
        self.assertEqual(REGION_OPERATION, "getBidPblancListInfoPrtcptPsblRgn")
        self.assertEqual(BASIS_AMOUNT_OPERATION, "getBidPblancListInfoServcBsisAmount")

    def test_parse_response_accepts_list_and_success_code(self):
        page = parse_response({
            "response": {"header": {"resultCode": "00"}, "body": {"totalCount": 1, "items": [{"bidNtceNo": "1"}]}}
        }, page_no=1, rows=100)
        self.assertEqual(page.items, [{"bidNtceNo": "1"}])
        self.assertEqual(page.total_count, 1)

    def test_parse_response_rejects_api_error_without_exposing_request(self):
        with self.assertRaises(G2BError) as caught:
            parse_response({"response": {"header": {"resultCode": "22", "resultMsg": "LIMIT"}}}, page_no=1, rows=100)
        self.assertEqual(caught.exception.code, "22")

    @override_settings(
        G2B_BID_API_ENDPOINT="https://apis.data.go.kr/1230000/ad/BidPublicInfoService",
        G2B_API_SERVICE_KEY="abc%2Fdef%3D",
        G2B_API_TIMEOUT_SECONDS=20,
    )
    def test_encoded_portal_key_is_not_double_encoded(self):
        payload = {"response": {"header": {"resultCode": "00"}, "body": {"totalCount": 0, "items": []}}}
        captured = {}

        def fake_open(request, timeout):
            captured["url"] = request.full_url
            return Response(payload)

        with mock.patch("geoflow_ops.bids.client.urlopen", side_effect=fake_open):
            G2BClient().fetch_page(NOTICE_OPERATION, datetime(2026, 9, 1), datetime(2026, 9, 2))
        self.assertIn("serviceKey=abc%2Fdef%3D", captured["url"])
        self.assertNotIn("%252F", captured["url"])

    @override_settings(
        G2B_BID_API_ENDPOINT="http://example.com/api",
        G2B_API_SERVICE_KEY="dummy",
        G2B_API_TIMEOUT_SECONDS=20,
    )
    def test_endpoint_allowlist_is_fail_closed(self):
        with self.assertRaises(G2BError) as caught:
            G2BClient()
        self.assertEqual(caught.exception.code, "INVALID_ENDPOINT")


class BidMatcherTests(TestCase):
    def test_same_kind_or_cross_kind_and_exclude_precedence(self):
        filters = {
            "region": [{"code": "30", "name": "대전광역시", "aliases": ["대전"]}],
            "industry": [{"code": "SURVEY", "name": "측량업", "aliases": []}],
            "include": [{"keyword": "지하시설물"}, {"keyword": "GIS"}],
            "exclude": [{"keyword": "건축설계"}],
        }
        notice = {
            "title": "대전 지하시설물 GIS DB 구축",
            "region_text": "대전광역시",
            "industry_text": "측량업",
            "search_text": "대전 지하시설물 GIS DB 구축 측량업",
        }
        self.assertTrue(evaluate_notice(notice, filters).matched)
        notice["search_text"] += " 건축설계"
        self.assertFalse(evaluate_notice(notice, filters).matched)

    def test_missing_structured_region_is_kept_for_review(self):
        result = evaluate_notice(
            {"title": "지하시설물 조사", "region_text": "", "industry_text": "", "search_text": "지하시설물 조사"},
            {"region": [{"code": "30", "name": "대전광역시", "aliases": ["대전"]}], "include": [{"keyword": "지하시설물"}]},
        )
        self.assertTrue(result.matched)
        self.assertTrue(result.needs_review)

    def test_no_rows_for_filter_kind_means_no_restriction(self):
        result = evaluate_notice(
            {"title": "측량 용역", "region_text": "제주", "industry_text": "", "search_text": "측량 용역"},
            {"include": [{"keyword": "측량"}]},
        )
        self.assertTrue(result.matched)

    def test_no_positive_filter_does_not_match_every_notice(self):
        result = evaluate_notice(
            {"title": "아무 용역", "region_text": "", "industry_text": "", "search_text": "아무 용역"},
            {"exclude": [{"keyword": "건축설계"}]},
        )
        self.assertFalse(result.matched)

    def test_nationwide_notice_matches_selected_region(self):
        result = evaluate_notice(
            {"title": "전국 대상 측량 용역", "region_text": "전국", "industry_text": "", "search_text": "전국 대상 측량 용역"},
            {"region": [{"code": "30", "name": "대전광역시", "aliases": ["대전"]}]},
        )
        self.assertTrue(result.matched)
        self.assertEqual(result.reasons[0]["values"], ["전국"])

    def test_unrestricted_industry_matches_selected_industry(self):
        result = evaluate_notice(
            {
                "title": "GIS 구축 용역",
                "region_text": "전국(지역제한 없음)",
                "industry_text": "업종제한 없음",
                "search_text": "GIS 구축 용역 전국 업종제한 없음",
            },
            {
                "region": [{"code": "30", "name": "대전광역시", "aliases": ["대전"]}],
                "industry": [{"code": "5023", "name": "공공측량업", "aliases": []}],
                "include": [{"keyword": "GIS"}],
            },
        )
        self.assertTrue(result.matched)
        self.assertFalse(result.needs_review)

    def test_definitive_keyword_mismatch_is_not_kept_for_review(self):
        result = evaluate_notice(
            {
                "title": "청사 정밀안전점검",
                "region_text": "",
                "industry_text": "",
                "search_text": "청사 정밀안전점검",
            },
            {
                "region": [{"code": "30", "name": "대전광역시", "aliases": ["대전"]}],
                "include": [{"keyword": "GIS"}],
            },
        )
        self.assertFalse(result.matched)
        self.assertFalse(result.needs_review)


class BidNormalizationTests(TestCase):
    def test_notice_join_key_normalizes_numeric_order_padding(self):
        from geoflow_ops.bids.sync import _key

        self.assertEqual(
            _key({"bidNtceNo": "R26BK01234567", "bidNtceOrd": "000"}),
            _key({"bidNtceNo": "R26BK01234567", "bidNtceOrd": "00"}),
        )

    def test_joined_values_uses_only_explicit_name_fields(self):
        from geoflow_ops.bids.sync import _joined_values

        rows = [{"lmtSno": 1, "prtcptLmtYn": "Y", "lcnsLmtNm": "공공측량업/5023"}]
        self.assertEqual(_joined_values(rows, ("lcnsLmtNm",)), "공공측량업/5023")

    def test_json_list_decodes_driver_text_without_iterating_characters(self):
        encoded = '[{"kind":"region","values":[]}]'
        self.assertEqual(_json_list(encoded), [{"kind": "region", "values": []}])
        self.assertEqual(_json_list({"kind": "region"}), [])

    def test_normalization_joins_auxiliary_constraints_by_notice(self):
        from geoflow_ops.bids.sync import _normalized_notice

        row = {
            "bidNtceNo": "R26BK01234567",
            "bidNtceOrd": "00",
            "bidNtceNm": "GIS DB 구축",
            "rgnLmtBidLocplcJdgmBssNm": "본사또는참여지사소재지",
            "dmndInsttCd": "DM001",
            "dmndInsttNm": "수요기관",
        }
        normalized = _normalized_notice(
            row,
            [{"prtcptPsblRgnNm": "대전광역시"}],
            [{"lcnsLmtNm": "공공측량업/5023", "permsnIndstrytyList": "수치지도제작업/5029"}],
            [],
            regions_complete=True,
            industries_complete=True,
        )
        self.assertEqual(normalized["region_text"], "대전광역시")
        self.assertNotIn("본사또는참여지사소재지", normalized["region_text"])
        self.assertEqual(normalized["industry_text"], "공공측량업/5023 / 수치지도제작업/5029")
        self.assertEqual(normalized["demand_agency_name"], "수요기관")

    def test_successful_empty_auxiliary_results_mean_no_restriction(self):
        from geoflow_ops.bids.sync import _normalized_notice

        normalized = _normalized_notice(
            {"bidNtceNo": "R26BK01234568", "bidNtceNm": "GIS 구축"},
            [],
            [],
            [],
            regions_complete=True,
            industries_complete=True,
        )
        self.assertEqual(normalized["region_text"], "전국(지역제한 없음)")
        self.assertEqual(normalized["industry_text"], "업종제한 없음")

    def test_declared_restriction_without_auxiliary_row_stays_uncertain(self):
        from geoflow_ops.bids.sync import _normalized_notice

        normalized = _normalized_notice(
            {
                "bidNtceNo": "R26BK01234569",
                "bidNtceNm": "GIS 구축",
                "rgnLmtYn": "Y",
                "indstrytyLmtYn": "Y",
            },
            [],
            [],
            [],
            regions_complete=True,
            industries_complete=True,
        )
        self.assertEqual(normalized["region_text"], "")
        self.assertEqual(normalized["industry_text"], "")


class BidSecurityTests(TestCase):
    def request(self, perms=(), roles=()):
        return SimpleNamespace(
            session={"gf_perms": list(perms), "gf_roles": list(roles)},
            _gf_perms_cache=set(perms),
            _gf_roles_cache=set(roles),
        )

    @mock.patch("geoflow_ops.bids.security_views.require_tenant_context", return_value="tenant_a")
    def test_list_requires_contract_read_permission(self, _tenant):
        with self.assertRaises(PermissionDenied):
            security_views._require_view(self.request())
        self.assertEqual(security_views._require_view(self.request(["contracts.view"])), "tenant_a")

    def test_manage_requires_write_permission_and_manager_role(self):
        self.assertFalse(security_views._can_manage(self.request(["contracts.view"], ["tenant_admin"])))
        self.assertFalse(security_views._can_manage(self.request(["contracts.create"], ["project_admin"])))
        self.assertTrue(security_views._can_manage(self.request(["contracts.create"], ["manager"])))


class BidSchemaContractTests(TestCase):
    def test_schema_is_tenant_owned_and_does_not_mix_filter_rules_into_ops_registry(self):
        migration = (Path(__file__).parent / "migrations" / "0036_bid_interest_foundation.py").read_text(encoding="utf-8")
        for relation in ("bid.filter_values", "bid.keyword_rules", "bid.notices", "bid.notice_revisions", "bid.notice_matches", "bid.notice_reviews", "bid.sync_runs"):
            self.assertIn(relation, migration)
        self.assertNotIn("INSERT INTO ops.settings_nodes", migration)
        self.assertNotIn("serviceKey", migration)
