"""Bounded live diagnostic, run only in an explicitly approved disposable runtime."""
import json
import time
from datetime import timedelta

from .policy import minute, canonical_order
from geoflow_ops.bids.client import G2BError


PROBE_ATTEMPTS = 3
PROBE_REQUEST_LIMIT = 9 * PROBE_ATTEMPTS
PROBE_TIMEOUT_SECONDS = 240
TRANSIENT_ERRORS = {'HTTP_500', 'HTTP_502', 'HTTP_503', 'HTTP_504', 'NETWORK_ERROR'}
STOP_ERRORS = TRANSIENT_ERRORS | {
    'MISSING_SERVICE_KEY', 'API_20', 'API_22', 'API_23', 'API_29', 'API_30', 'API_31',
    'TIME_BUDGET_EXHAUSTED', 'BUDGET_EXHAUSTED', 'DAILY_BUDGET_EXHAUSTED',
}


def run_probe(now, emit=print, client=None):
    from .client import Client, SEARCH, CHANGES, REGIONS, LICENSES

    client = client or Client(budget=PROBE_REQUEST_LIMIT)
    deadline = time.monotonic() + PROBE_TIMEOUT_SECONDS
    client.deadline = deadline

    def page_with_retry(label, operation, **query):
        # Retry the identical read only; no altered sample or validation bypass.
        for attempt in range(1, PROBE_ATTEMPTS + 1):
            if time.monotonic() + 30 >= deadline:
                raise G2BError('TIME_BUDGET_EXHAUSTED', '진단 시간 한도 초과')
            try:
                return client.page(operation, **query)
            except G2BError as exc:
                if exc.code not in TRANSIENT_ERRORS or attempt == PROBE_ATTEMPTS:
                    raise
                delay = 2 * attempt
                if time.monotonic() + delay + 30 >= deadline:
                    raise G2BError('TIME_BUDGET_EXHAUSTED', '진단 시간 한도 초과') from None
                emit(json.dumps(dict(check=label, ok=False, code=exc.code,
                                     attempt=attempt, retry_in_seconds=delay)))
                time.sleep(delay)

    end = minute(now).replace(hour=0, minute=0) - timedelta(minutes=1)
    start = end.replace(hour=0, minute=0)
    dates = dict(inqryBgnDt=start.strftime("%Y%m%d%H%M"), inqryEndDt=end.strftime("%Y%m%d%H%M"))
    sample = None
    failures = 0
    checks = [
        ("posted_basic", CHANGES, dict(dates, inqryDiv="1")),
        ("posted_search", SEARCH, dict(dates, inqryDiv="1")),
        ("industry_search", SEARCH, dict(dates, inqryDiv="1", indstrytyCd="5031",
                                         inqryBgnDt=(start - timedelta(days=6)).strftime("%Y%m%d%H%M"))),
        ("changed", CHANGES, dict(dates, inqryDiv="3")),
    ]
    for label, operation, query in checks:
        try:
            page = page_with_retry(label, operation, rows=1, **query)
            emit(json.dumps(dict(check=label, ok=True, total=page.total_count,
                                 start=query["inqryBgnDt"], end=query["inqryEndDt"])))
            # An unrestricted national notice cannot validate license linkage.
            if page.items and label == "industry_search":
                sample = page.items[0]
        except G2BError as exc:
            # Do not include provider messages, record fields, request URLs, or key.
            emit(json.dumps(dict(check=label, ok=False, code=exc.code)))
            failures += 1
            if exc.code in STOP_ERRORS:
                return False
    if not sample or not sample.get("bidNtceNo"):
        emit(json.dumps(dict(check="details", ok=False, code="NO_INDUSTRY_SAMPLE", skipped=True)))
        return False
    query = dict(inqryDiv="2", bidNtceNo=sample["bidNtceNo"], bidNtceOrd=sample.get("bidNtceOrd") or "00")
    for label, operation in (("regions", REGIONS), ("licenses", LICENSES)):
        try:
            page = page_with_retry(label, operation, rows=999 if label == "licenses" else 1, **query)
            linked = bool(page.items) and all(
                item.get("bidNtceNo") == sample["bidNtceNo"] and
                item.get("bidNtceOrd") not in (None, "") and
                canonical_order(item["bidNtceOrd"]) == canonical_order(query["bidNtceOrd"])
                for item in page.items)
            # Empty region/product results are not evidence of unrestricted eligibility.
            verified = linked if label == "licenses" else not page.items or linked
            if not verified:
                failures += 1
            emit(json.dumps(dict(check=label, ok=verified, total=page.total_count,
                                 sample_source="industry_5031", notice_key_matches=linked,
                                 returned_rows=len(page.items),
                                 code="VERIFIED" if linked else "DETAILS_REQUIRE_REVIEW")))
        except G2BError as exc:
            emit(json.dumps(dict(check=label, ok=False, code=exc.code)))
            failures += 1
            if exc.code in STOP_ERRORS:
                return False
    try:
        # The official service-notice schema has neither rgnLmtYn nor prtcptLmtYn.
        # Obtain a positive sample from the regional detail endpoint itself.
        page = page_with_retry("regional_sample", REGIONS, rows=999, inqryDiv="1", **dict(
            dates, inqryBgnDt=(start - timedelta(days=6)).strftime("%Y%m%d%H%M")))
        regional_sample = next((row for row in page.items
                                if "용역" in str(row.get("bsnsDivNm") or "")
                                and row.get("bidNtceNo")
                                and row.get("bidNtceOrd") not in (None, "")
                                and str(row.get("prtcptPsblRgnNm") or "").strip()), None)
        emit(json.dumps(dict(check="regional_sample", ok=bool(regional_sample),
                             total=page.total_count, returned_rows=len(page.items),
                             code="SAMPLE_FOUND" if regional_sample else "NO_RESTRICTED_REGION_SAMPLE")))
        if regional_sample is None:
            return False
        # Independently prove the sample belongs to a service notice and order.
        service_page = page_with_retry("regional_service_notice", CHANGES, rows=999, inqryDiv="2",
                                   bidNtceNo=regional_sample["bidNtceNo"])
        service_linked = any(
            item.get("bidNtceNo") == regional_sample["bidNtceNo"] and
            item.get("bidNtceOrd") not in (None, "") and
            canonical_order(item["bidNtceOrd"]) == canonical_order(regional_sample["bidNtceOrd"])
            for item in service_page.items)
        emit(json.dumps(dict(check="regional_service_notice", ok=service_linked,
                             notice_key_matches=service_linked)))
        if not service_linked:
            return False
        page = page_with_retry("restricted_region", REGIONS, rows=999, inqryDiv="2", bidNtceNo=regional_sample["bidNtceNo"],
                           bidNtceOrd=regional_sample.get("bidNtceOrd") or "00")
        linked = bool(page.items) and all(
            item.get("bidNtceNo") == regional_sample["bidNtceNo"] and
            item.get("bidNtceOrd") not in (None, "") and
            canonical_order(item["bidNtceOrd"]) == canonical_order(regional_sample.get("bidNtceOrd"))
            for item in page.items)
        named = linked and all(str(item.get("prtcptPsblRgnNm") or "").strip() for item in page.items)
        emit(json.dumps(dict(check="restricted_region", ok=named, total=page.total_count,
                             notice_key_matches=linked, region_name_present=named)))
        return failures == 0 and named
    except G2BError as exc:
        emit(json.dumps(dict(check="restricted_region", ok=False, code=exc.code)))
        return False
