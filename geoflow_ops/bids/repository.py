from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any
from uuid import UUID

from django.db import connections, transaction

from .matcher import evaluate_notice


FILTER_KINDS = {"region", "industry", "agency"}
KEYWORD_TYPES = {"include", "exclude"}
REVIEW_STATUSES = {"unreviewed", "reviewing", "interested", "considering", "excluded"}


def actor(request) -> str:
    user = getattr(request, "user", None)
    return str(getattr(user, "email", None) or getattr(user, "username", None) or getattr(user, "pk", ""))[:255]


def uuid_or_none(value: object) -> UUID | None:
    try:
        return UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return None


def load_filters(alias: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with connections[alias].cursor() as cur:
        cur.execute(
            "SELECT id::text,kind,code,name,aliases FROM bid.filter_values WHERE active=true ORDER BY kind,ord,name"
        )
        for row in cur.fetchall():
            result[row[1]].append({"id": row[0], "code": row[2], "name": row[3], "aliases": row[4] or []})
        cur.execute(
            "SELECT id::text,rule_type,keyword FROM bid.keyword_rules WHERE active=true ORDER BY rule_type,ord,keyword"
        )
        for row in cur.fetchall():
            result[row[1]].append({"id": row[0], "keyword": row[2]})
    return dict(result)


def list_settings(alias: str) -> dict[str, list[dict[str, Any]]]:
    result: dict[str, list[dict[str, Any]]] = defaultdict(list)
    with connections[alias].cursor() as cur:
        cur.execute(
            "SELECT id::text,kind,code,name,aliases,active,ord FROM bid.filter_values ORDER BY kind,ord,name"
        )
        for row in cur.fetchall():
            result[row[1]].append({
                "id": row[0], "kind": row[1], "code": row[2], "name": row[3],
                "aliases": row[4] or [], "active": bool(row[5]), "ord": row[6],
            })
        cur.execute(
            "SELECT id::text,rule_type,keyword,active,ord FROM bid.keyword_rules ORDER BY rule_type,ord,keyword"
        )
        for row in cur.fetchall():
            result[row[1]].append({
                "id": row[0], "rule_type": row[1], "keyword": row[2],
                "active": bool(row[3]), "ord": row[4],
            })
    return dict(result)


def save_filter_value(alias: str, data: dict[str, Any]) -> None:
    kind = str(data.get("kind") or "").strip().lower()
    code = str(data.get("code") or "").strip()[:120]
    name = str(data.get("name") or "").strip()[:255]
    if kind not in FILTER_KINDS or not code or not name:
        raise ValueError("지역·업종·기관의 구분, 코드, 이름을 확인하세요.")
    aliases = [value.strip()[:255] for value in str(data.get("aliases") or "").split(",") if value.strip()]
    active = str(data.get("active") or "").lower() in {"1", "true", "yes", "on"}
    try:
        ord_value = int(data.get("ord")) if data.get("ord") not in (None, "") else None
    except (TypeError, ValueError):
        ord_value = None
    row_id = uuid_or_none(data.get("record_id"))
    with transaction.atomic(using=alias), connections[alias].cursor() as cur:
        if row_id:
            cur.execute(
                "UPDATE bid.filter_values SET kind=%s,code=%s,name=%s,aliases=%s,active=%s,ord=COALESCE(%s,ord),updated_at=now() WHERE id=%s",
                [kind, code, name, aliases, active, ord_value, row_id],
            )
            if cur.rowcount != 1:
                raise ValueError("설정 항목을 찾을 수 없습니다.")
        else:
            cur.execute(
                "INSERT INTO bid.filter_values(kind,code,name,aliases,active,ord) VALUES (%s,%s,%s,%s,%s,%s)",
                [kind, code, name, aliases, active, ord_value or 0],
            )


def save_keyword(alias: str, data: dict[str, Any]) -> None:
    rule_type = str(data.get("rule_type") or "").strip().lower()
    keyword = str(data.get("keyword") or "").strip()[:200]
    if rule_type not in KEYWORD_TYPES or not keyword:
        raise ValueError("포함·제외 구분과 키워드를 확인하세요.")
    active = str(data.get("active") or "").lower() in {"1", "true", "yes", "on"}
    try:
        ord_value = int(data.get("ord")) if data.get("ord") not in (None, "") else None
    except (TypeError, ValueError):
        ord_value = None
    row_id = uuid_or_none(data.get("record_id"))
    with transaction.atomic(using=alias), connections[alias].cursor() as cur:
        if row_id:
            cur.execute(
                "UPDATE bid.keyword_rules SET rule_type=%s,keyword=%s,active=%s,ord=COALESCE(%s,ord),updated_at=now() WHERE id=%s",
                [rule_type, keyword, active, ord_value, row_id],
            )
            if cur.rowcount != 1:
                raise ValueError("키워드를 찾을 수 없습니다.")
        else:
            cur.execute(
                "INSERT INTO bid.keyword_rules(rule_type,keyword,active,ord) VALUES (%s,%s,%s,%s)",
                [rule_type, keyword, active, ord_value or 0],
            )


def reevaluate_all(alias: str) -> int:
    filters = load_filters(alias)
    changed = 0
    with connections[alias].cursor() as cur:
        cur.execute(
            "SELECT id::text,title,COALESCE(region_text,''),COALESCE(industry_text,''),"
            "COALESCE(notice_agency_name,''),COALESCE(demand_agency_name,''),raw_payload "
            "FROM bid.notices"
        )
        rows = cur.fetchall()
    with transaction.atomic(using=alias), connections[alias].cursor() as cur:
        for row in rows:
            notice = {
                "title": row[1], "region_text": row[2], "industry_text": row[3],
                "notice_agency_name": row[4], "demand_agency_name": row[5],
                "search_text": " ".join([row[1] or "", row[2], row[3], row[4], row[5], json.dumps(row[6] or {}, ensure_ascii=False)]),
            }
            result = evaluate_notice(notice, filters)
            cur.execute(
                """INSERT INTO bid.notice_matches(notice_id,matched,needs_review,reasons,evaluated_at)
                   VALUES (%s,%s,%s,%s::jsonb,now())
                   ON CONFLICT (notice_id) DO UPDATE SET matched=excluded.matched,
                     needs_review=excluded.needs_review,reasons=excluded.reasons,evaluated_at=now()""",
                [row[0], result.matched, result.needs_review, json.dumps(result.reasons, ensure_ascii=False)],
            )
            changed += 1
    return changed


def list_notices(alias: str, *, query: str = "", review_status: str = "", include_all: bool = False) -> list[dict[str, Any]]:
    where = ["(%s OR COALESCE(m.matched,false)=true OR COALESCE(m.needs_review,false)=true)"]
    params: list[Any] = [include_all]
    if query:
        where.append("(n.title ILIKE %s OR n.bid_notice_no ILIKE %s OR n.notice_agency_name ILIKE %s OR n.demand_agency_name ILIKE %s)")
        like = f"%{query[:100]}%"
        params.extend([like, like, like, like])
    if review_status in REVIEW_STATUSES:
        where.append("COALESCE(r.status,'unreviewed')=%s")
        params.append(review_status)
    else:
        where.append("COALESCE(r.status,'unreviewed')<>'excluded'")
    sql = f"""
        SELECT n.id::text,n.bid_notice_no,n.bid_notice_ord,n.title,
               COALESCE(n.notice_agency_name,''),COALESCE(n.demand_agency_name,''),
               n.posted_at,n.bid_close_at,n.basic_amount,n.estimated_price,n.budget_amount,
               COALESCE(n.region_text,''),COALESCE(n.industry_text,''),n.detail_url,
               CASE WHEN n.notice_status<>'cancelled' AND n.bid_close_at<=now() THEN 'closed' ELSE n.notice_status END,
               n.is_correction,COALESCE(m.matched,false),
               COALESCE(m.needs_review,false),COALESCE(m.reasons,'[]'::jsonb),
               COALESCE(r.status,'unreviewed'),COALESCE(r.memo,'')
          FROM bid.notices n
          LEFT JOIN bid.notice_matches m ON m.notice_id=n.id
          LEFT JOIN bid.notice_reviews r ON r.notice_id=n.id
         WHERE {' AND '.join(where)}
         ORDER BY n.bid_close_at NULLS LAST,n.posted_at DESC NULLS LAST
         LIMIT 1000
    """
    with connections[alias].cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    keys = [
        "id","bid_notice_no","bid_notice_ord","title","notice_agency_name","demand_agency_name",
        "posted_at","bid_close_at","basic_amount","estimated_price","budget_amount","region_text",
        "industry_text","detail_url","notice_status","is_correction","matched","needs_review",
        "reasons","review_status","memo",
    ]
    return [dict(zip(keys, row)) for row in rows]


def save_review(alias: str, notice_id: UUID, *, status: str, memo: str, updated_by: str) -> None:
    if status not in REVIEW_STATUSES:
        raise ValueError("검토 상태를 확인하세요.")
    with transaction.atomic(using=alias), connections[alias].cursor() as cur:
        cur.execute("SELECT 1 FROM bid.notices WHERE id=%s", [notice_id])
        if not cur.fetchone():
            raise ValueError("입찰공고를 찾을 수 없습니다.")
        cur.execute(
            """INSERT INTO bid.notice_reviews(notice_id,status,memo,updated_by,updated_at)
               VALUES (%s,%s,%s,%s,now()) ON CONFLICT (notice_id) DO UPDATE SET
               status=excluded.status,memo=excluded.memo,updated_by=excluded.updated_by,updated_at=now()""",
            [notice_id, status, memo[:2000] or None, updated_by],
        )


def latest_sync(alias: str) -> dict[str, Any] | None:
    with connections[alias].cursor() as cur:
        cur.execute(
            "SELECT status,fetched_count,inserted_count,updated_count,matched_count,error_message,started_at,finished_at "
            "FROM bid.sync_runs ORDER BY started_at DESC LIMIT 1"
        )
        row = cur.fetchone()
    if not row:
        return None
    keys = ["status","fetched_count","inserted_count","updated_count","matched_count","error_message","started_at","finished_at"]
    return dict(zip(keys, row))
