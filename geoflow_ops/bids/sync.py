from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from zoneinfo import ZoneInfo
from urllib.parse import urlparse

from django.db import connections, transaction
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from .client import (
    BASIS_AMOUNT_OPERATION,
    LICENSE_OPERATION,
    NOTICE_OPERATION,
    REGION_OPERATION,
    G2BClient,
    G2BError,
)
from .repository import reevaluate_all


SEOUL = ZoneInfo("Asia/Seoul")


def _value(row: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value not in (None, ""):
            return value
    return None


def _text(row: dict[str, Any], *keys: str) -> str:
    return str(_value(row, *keys) or "").strip()


def _date(value: object) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    parsed = parse_datetime(text)
    if parsed is None:
        for fmt in ("%Y%m%d%H%M", "%Y%m%d%H%M%S", "%Y-%m-%d %H:%M:%S"):
            try:
                parsed = datetime.strptime(text, fmt)
                break
            except ValueError:
                continue
    if parsed is None:
        return None
    return parsed.replace(tzinfo=SEOUL) if timezone.is_naive(parsed) else parsed


def _money(value: object) -> Decimal | None:
    try:
        return Decimal(str(value).replace(",", "").strip()).quantize(Decimal("1")) if value not in (None, "") else None
    except (InvalidOperation, ValueError):
        return None


def _key(row: dict[str, Any]) -> tuple[str, str]:
    return (_text(row, "bidNtceNo"), _text(row, "bidNtceOrd") or "00")


def _detail_url(value: object) -> str | None:
    url = str(value or "").strip()
    if not url:
        return None
    parsed = urlparse(url)
    host = str(parsed.hostname or "").casefold()
    if parsed.scheme != "https" or not (host == "g2b.go.kr" or host.endswith(".g2b.go.kr")):
        return None
    return url


def _group(rows: list[dict[str, Any]]) -> dict[tuple[str, str], list[dict[str, Any]]]:
    result: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if _key(row)[0]:
            result[_key(row)].append(row)
    return result


def _joined_values(rows: list[dict[str, Any]], keys: tuple[str, ...]) -> str:
    values: list[str] = []
    for row in rows:
        for key in keys:
            value = row.get(key)
            if value not in (None, ""):
                values.extend(part.strip() for part in str(value).split(",") if part.strip())
    return " / ".join(dict.fromkeys(value for value in values if value))


def _normalized_notice(row: dict[str, Any], regions: list[dict[str, Any]], industries: list[dict[str, Any]], basis: list[dict[str, Any]]) -> dict[str, Any]:
    merged_basis = basis[0] if basis else {}
    title = _text(row, "bidNtceNm")
    notice_kind = _text(row, "ntceKindNm")
    close_at = _date(_value(row, "bidClseDt"))
    status = "closed" if close_at and close_at <= timezone.now() else "open"
    if "취소" in title or "취소" in notice_kind:
        status = "cancelled"
    raw = {"notice": row, "regions": regions, "industries": industries, "basis_amount": basis}
    canonical = json.dumps(raw, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    region_text = _joined_values(regions, (
        "prtcptPsblRgnNm", "prtcptLmtRgnNm", "rbidLmtRgnNm",
        "rgnLmtBidLocplcJdgmBssNm", "regionNm",
    )) or _text(
        row, "prtcptPsblRgnNm", "prtcptLmtRgnNm", "rbidLmtRgnNm",
        "rgnLmtBidLocplcJdgmBssNm",
    )
    industry_text = _joined_values(industries, (
        "lcnsLmtNm", "licenseNm", "licenseKindNm", "indstrytyNm",
        "indstrytyLmtNm", "bidprcPsblIndstrytyNm", "permsnIndstrytyList",
    )) or _text(
        row, "bidprcPsblIndstrytyNm", "lcnsLmtNm", "indstrytyNm", "licenseNm",
    )
    return {
        "bid_notice_no": _text(row, "bidNtceNo"),
        "bid_notice_ord": _text(row, "bidNtceOrd") or "00",
        "title": title,
        "notice_kind": notice_kind,
        "notice_agency_code": _text(row, "ntceInsttCd"),
        "notice_agency_name": _text(row, "ntceInsttNm"),
        "demand_agency_code": _text(row, "dminsttCd"),
        "demand_agency_name": _text(row, "dminsttNm"),
        "bid_method_name": _text(row, "bidMethdNm"),
        "contract_method_name": _text(row, "cntrctCnclsMthdNm"),
        "region_text": region_text,
        "industry_text": industry_text,
        "region_items": regions,
        "industry_items": industries,
        "posted_at": _date(_value(row, "bidNtceDt", "rgstDt")),
        "bid_begin_at": _date(_value(row, "bidBeginDt")),
        "bid_close_at": close_at,
        "open_at": _date(_value(row, "opengDt")),
        "basic_amount": _money(_value(merged_basis, "bssamt", "bssAmt", "basisAmount")),
        "estimated_price": _money(_value(row, "presmptPrce")),
        "budget_amount": _money(_value(row, "asignBdgtAmt")),
        "detail_url": _detail_url(_value(row, "bidNtceDtlUrl")),
        "notice_status": status,
        "is_correction": any(word in f"{title} {notice_kind}" for word in ("정정", "변경")),
        "payload_hash": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "raw_payload": raw,
        "source_updated_at": _date(_value(row, "chgDt", "rgstDt")),
    }


def _optional(client: G2BClient, operation: str, start: datetime, end: datetime) -> tuple[list[dict[str, Any]], str | None]:
    try:
        return client.fetch_all(operation, start, end), None
    except G2BError as exc:
        return [], exc.code


def sync_service_notices(alias: str, start: datetime, end: datetime, *, client: G2BClient | None = None) -> dict[str, Any]:
    if not alias or alias == "default":
        raise ValueError("명시적인 테넌트 데이터베이스가 필요합니다.")
    if end <= start:
        raise ValueError("조회 종료시각은 시작시각보다 늦어야 합니다.")
    client = client or G2BClient()
    with connections[alias].cursor() as cur:
        cur.execute(
            "INSERT INTO bid.sync_runs(operation,status,window_start,window_end) VALUES (%s,'running',%s,%s) RETURNING id::text",
            [NOTICE_OPERATION, start, end],
        )
        run_id = cur.fetchone()[0]
    try:
        notices = client.fetch_all(NOTICE_OPERATION, start, end)
        with ThreadPoolExecutor(max_workers=3, thread_name_prefix="g2b-aux") as pool:
            region_future = pool.submit(_optional, client, REGION_OPERATION, start, end)
            industry_future = pool.submit(_optional, client, LICENSE_OPERATION, start, end)
            basis_future = pool.submit(_optional, client, BASIS_AMOUNT_OPERATION, start, end)
            region_rows, region_error = region_future.result()
            industry_rows, industry_error = industry_future.result()
            basis_rows, basis_error = basis_future.result()
        regions = _group(region_rows)
        industries = _group(industry_rows)
        basis = _group(basis_rows)
        inserted = updated = 0
        with transaction.atomic(using=alias), connections[alias].cursor() as cur:
            for source in notices:
                key = _key(source)
                if not key[0]:
                    continue
                row = _normalized_notice(source, regions.get(key, []), industries.get(key, []), basis.get(key, []))
                cur.execute(
                    "SELECT payload_hash FROM bid.notices WHERE source='g2b' AND bid_notice_no=%s AND bid_notice_ord=%s",
                    [row["bid_notice_no"], row["bid_notice_ord"]],
                )
                existing = cur.fetchone()
                cur.execute(
                    """INSERT INTO bid.notices(
                        source,bid_notice_no,bid_notice_ord,business_type,title,notice_kind,
                        notice_agency_code,notice_agency_name,demand_agency_code,demand_agency_name,
                        bid_method_name,contract_method_name,region_text,industry_text,region_items,
                        industry_items,posted_at,bid_begin_at,bid_close_at,open_at,basic_amount,
                        estimated_price,budget_amount,detail_url,notice_status,is_correction,payload_hash,
                        raw_payload,source_updated_at,last_seen_at,updated_at)
                       VALUES ('g2b',%s,%s,'service',%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s::jsonb,
                         %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::jsonb,%s,now(),now())
                       ON CONFLICT(source,bid_notice_no,bid_notice_ord) DO UPDATE SET
                         title=excluded.title,notice_kind=excluded.notice_kind,
                         notice_agency_code=excluded.notice_agency_code,notice_agency_name=excluded.notice_agency_name,
                         demand_agency_code=excluded.demand_agency_code,demand_agency_name=excluded.demand_agency_name,
                         bid_method_name=excluded.bid_method_name,contract_method_name=excluded.contract_method_name,
                         region_text=excluded.region_text,industry_text=excluded.industry_text,
                         region_items=excluded.region_items,industry_items=excluded.industry_items,
                         posted_at=excluded.posted_at,bid_begin_at=excluded.bid_begin_at,
                         bid_close_at=excluded.bid_close_at,open_at=excluded.open_at,basic_amount=excluded.basic_amount,
                         estimated_price=excluded.estimated_price,budget_amount=excluded.budget_amount,
                         detail_url=excluded.detail_url,notice_status=excluded.notice_status,
                         is_correction=(excluded.is_correction OR bid.notices.payload_hash<>excluded.payload_hash),
                         payload_hash=excluded.payload_hash,
                         raw_payload=excluded.raw_payload,source_updated_at=excluded.source_updated_at,
                         last_seen_at=now(),updated_at=CASE WHEN bid.notices.payload_hash<>excluded.payload_hash THEN now() ELSE bid.notices.updated_at END
                       RETURNING id::text""",
                    [
                        row["bid_notice_no"], row["bid_notice_ord"], row["title"], row["notice_kind"],
                        row["notice_agency_code"], row["notice_agency_name"], row["demand_agency_code"],
                        row["demand_agency_name"], row["bid_method_name"], row["contract_method_name"],
                        row["region_text"], row["industry_text"], json.dumps(row["region_items"], ensure_ascii=False),
                        json.dumps(row["industry_items"], ensure_ascii=False), row["posted_at"], row["bid_begin_at"],
                        row["bid_close_at"], row["open_at"], row["basic_amount"], row["estimated_price"],
                        row["budget_amount"], row["detail_url"], row["notice_status"], row["is_correction"],
                        row["payload_hash"], json.dumps(row["raw_payload"], ensure_ascii=False), row["source_updated_at"],
                    ],
                )
                notice_id = cur.fetchone()[0]
                cur.execute(
                    """INSERT INTO bid.notice_revisions(notice_id,payload_hash,raw_payload)
                       VALUES (%s,%s,%s::jsonb) ON CONFLICT(notice_id,payload_hash) DO NOTHING""",
                    [notice_id, row["payload_hash"], json.dumps(row["raw_payload"], ensure_ascii=False)],
                )
                if existing is None:
                    inserted += 1
                elif existing[0] != row["payload_hash"]:
                    updated += 1
        evaluated = reevaluate_all(alias)
        matched = 0
        with connections[alias].cursor() as cur:
            cur.execute("SELECT count(*) FROM bid.notice_matches WHERE matched=true")
            matched = int(cur.fetchone()[0])
        auxiliary_errors = [code for code in (region_error, industry_error, basis_error) if code]
        status = "partial" if auxiliary_errors else "success"
        error_message = "보조정보 일부 조회 실패: " + ", ".join(auxiliary_errors) if auxiliary_errors else None
        with connections[alias].cursor() as cur:
            cur.execute(
                """UPDATE bid.sync_runs SET status=%s,fetched_count=%s,inserted_count=%s,
                   updated_count=%s,matched_count=%s,error_code=%s,error_message=%s,finished_at=now() WHERE id=%s""",
                [status, len(notices), inserted, updated, matched, auxiliary_errors[0] if auxiliary_errors else None, error_message, run_id],
            )
        return {"status": status, "fetched": len(notices), "inserted": inserted, "updated": updated, "evaluated": evaluated, "matched": matched}
    except Exception as exc:
        code = exc.code if isinstance(exc, G2BError) else "SYNC_ERROR"
        with connections[alias].cursor() as cur:
            cur.execute(
                "UPDATE bid.sync_runs SET status='failed',error_code=%s,error_message=%s,finished_at=now() WHERE id=%s",
                [str(code)[:100], str(exc)[:1000], run_id],
            )
        raise
