"""Bounded live diagnostic, run only in an explicitly approved disposable runtime."""
import json
from datetime import timedelta

from .client import Client, SEARCH, CHANGES, REGIONS, LICENSES, PRODUCTS
from .policy import minute, canonical_order
from geoflow_ops.bids.client import G2BError


def run_probe(now, emit=print, client=None):
    client = client or Client(budget=7)
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
            page = client.page(operation, rows=1, **query)
            emit(json.dumps(dict(check=label, ok=True, total=page.total_count,
                                 start=query["inqryBgnDt"], end=query["inqryEndDt"])))
            # An unrestricted national notice cannot validate license linkage.
            if page.items and label == "industry_search":
                sample = page.items[0]
        except G2BError as exc:
            # Do not include provider messages, record fields, request URLs, or key.
            emit(json.dumps(dict(check=label, ok=False, code=exc.code)))
            failures += 1
            if exc.code in {"MISSING_SERVICE_KEY", "API_20", "API_22", "API_23", "API_29", "API_30", "API_31", "NETWORK_ERROR"}:
                return False
    if not sample or not sample.get("bidNtceNo"):
        emit(json.dumps(dict(check="details", ok=False, code="NO_INDUSTRY_SAMPLE", skipped=True)))
        return False
    query = dict(inqryDiv="2", bidNtceNo=sample["bidNtceNo"], bidNtceOrd=sample.get("bidNtceOrd") or "00")
    for label, operation in (("regions", REGIONS), ("licenses", LICENSES), ("products", PRODUCTS)):
        try:
            page = client.page(operation, rows=999 if label == "licenses" else 1, **query)
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
            if exc.code in {"API_22", "API_23", "NETWORK_ERROR"}:
                break
    return failures == 0
