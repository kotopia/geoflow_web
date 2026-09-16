import json
import re
from contextlib import contextmanager
from datetime import timedelta

from django.conf import settings
from django.core.serializers.json import DjangoJSONEncoder
from django.db import connections, transaction
from django.db.models import F
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from geoflow_ops.bids.client import G2BError
from geoflow_ops.bids.sync import _normalized_notice
from geoflow_ops.bids.matcher import keyword_matches
from .client import Client
from .models import CollectionJob, CollectionRule, Notice, NoticeRevision, CollectionWindow, ApiBudget
from .policy import retention_start, minute, next_window, canonical_order, notice_id


def central_alias():
    return getattr(settings, "CENTRAL_DB_ALIAS", "default")


def enabled(alias):
    if not alias or alias == central_alias():
        raise ValueError("명시적인 회사 데이터베이스가 필요합니다.")
    return alias in getattr(settings, "G2B_CENTRAL_TENANT_ALIASES", ())


def enqueue_rule(rule, now=None):
    now = minute(now or timezone.now())
    job, created = CollectionJob.objects.using(central_alias()).get_or_create(
        rule=rule, defaults=dict(backfill_cursor=retention_start(now), backfill_end=now,
                                 backfill_start=retention_start(now),
                                 live_cursor=now, due_at=now),
    )
    if not created:
        CollectionJob.objects.using(central_alias()).filter(pk=job.pk).update(requested=True)
    return job


def request_sync():
    # Only active central rules; a tenant cannot expand the shared collection scope.
    return CollectionJob.objects.using(central_alias()).filter(rule__active=True).update(requested=True)


@contextmanager
def worker_lock():
    conn = connections[central_alias()]
    if conn.vendor != "postgresql":
        raise RuntimeError("중앙 수집기는 PostgreSQL에서만 실행합니다.")
    with conn.cursor() as cur:
        cur.execute("SELECT pg_try_advisory_lock(714302611)")
        acquired = cur.fetchone()[0]
    try:
        yield acquired
    finally:
        if acquired:
            with conn.cursor() as cur:
                cur.execute("SELECT pg_advisory_unlock(714302611)")


def rule_matches(rule, row, details):
    if rule.kind == "keyword":
        return keyword_matches(rule.value, row.get("bidNtceNm"))
    # Preserve token boundaries: code 1468 must not match 11468.
    text = json.dumps(details["industries"], ensure_ascii=False)
    return re.search(r"(?<!\d)" + re.escape(rule.value) + r"(?!\d)", text) is not None


def store_notice(row, details, rule, now):
    normalized = _normalized_notice(row, details["regions"], details["industries"], [])
    posted = normalized["posted_at"]
    if not posted:
        raise G2BError("MISSING_POSTED_DATE", "공고게시일을 확인할 수 없습니다.")
    if posted < retention_start(now):
        return
    # Never infer 'no restrictions' from an empty successful auxiliary response.
    summary = json.loads(json.dumps(normalized, cls=DjangoJSONEncoder))
    raw = dict(normalized["raw_payload"], products=details["products"])
    import hashlib
    digest = hashlib.sha256(json.dumps(raw, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    summary.pop("raw_payload", None)
    summary["industry_parse_status"] = "review_required" if details["industries"] else "unknown"
    summary["direct_production_parse_status"] = "unknown"
    alias = central_alias()
    with transaction.atomic(using=alias):
        old_hash = Notice.objects.using(alias).filter(id=notice_id(normalized["bid_notice_no"], normalized["bid_notice_ord"])).values_list("payload_hash", flat=True).first()
        notice, _ = Notice.objects.using(alias).update_or_create(
            id=notice_id(normalized["bid_notice_no"], normalized["bid_notice_ord"]),
            defaults=dict(number=normalized["bid_notice_no"], order=canonical_order(normalized["bid_notice_ord"]),
                          title=normalized["title"], posted_at=posted, close_at=normalized["bid_close_at"],
                          agency=normalized["notice_agency_name"], demand_agency=normalized["demand_agency_name"],
                          estimated_price=normalized["estimated_price"], region_text=normalized["region_text"],
                          industry_text=normalized["industry_text"], region_known=bool(normalized["region_text"]),
                          industry_known=bool(normalized["industry_text"]), summary=summary, raw=raw,
                          payload_hash=digest, source_updated_at=normalized["source_updated_at"], last_seen_at=now),
        )
        notice.rules.add(rule)
        NoticeRevision.objects.using(alias).get_or_create(notice=notice, payload_hash=digest, defaults={"raw": raw})
        outcome = "inserted" if old_hash is None else "updated" if old_hash != digest else "unchanged"
        if outcome != "unchanged":
            counter, _ = ApiBudget.objects.using(alias).get_or_create(day=minute(now).date())
            ApiBudget.objects.using(alias).filter(pk=counter.pk).update(**{outcome: F(outcome) + 1})
    return outcome


def run_step(job, client, now=None, mode=None):
    """Persist per-notice; advance the cursor only after the entire window succeeds.

    Retrying a partially persisted window is safe. Errors expose codes only.
    """
    now = minute(now or timezone.now())
    alias = central_alias()
    if not CollectionRule.objects.using(alias).filter(pk=job.rule_id, active=True).exists():
        return False
    live = (job.requested or job.due_at <= now) if mode is None else mode == "live"
    from .period import selection, bounds, select_checkpoint
    scope_signature = selection(now)["signature"] if not live else None
    def check_scope():
        if not live and selection(now)["signature"] != scope_signature:
            raise G2BError("SCOPE_CHANGED", "수집 기간이 변경되어 다음 실행에서 새 범위를 적용합니다.")
    if live:
        start, end = next_window(max(job.live_cursor, retention_start(now)), now)
    else:
        from .lifecycle import recent_backfill_window
        gap = recent_backfill_window(job, now)
        if not gap:
            from .lifecycle import coverage_gap
            state = "BACKFILL_COMPLETE" if coverage_gap(job, now) is None else "RANGE_COMPLETE"
            CollectionJob.objects.using(alias).filter(pk=job.pk, generation=job.generation).update(backfill_status=state)
            return False
        start, end = gap
    if live:
        start -= timedelta(hours=2)
    lane = "incremental_progress" if live else "backfill_progress"
    previous = getattr(job, lane) or {}
    if not previous and job.status in {"failed", "running"} and job.progress.get("mode") == ("live" if live else "backfill"):
        previous = job.progress
    suspended = []
    if not live:
        previous, suspended = select_checkpoint(previous, *bounds(job, now))
    # Freeze an incomplete window, including its rejected rows, across retries.
    # Advancing the live end on every retry can repeatedly exhaust the budget.
    resume = not previous.get("finished") and previous.get("checkpoint_version") == 1
    if resume:
        live = previous["mode"] == "live"
        start, end = parse_datetime(previous["start"]), parse_datetime(previous["end"])
    outcomes = previous.get("outcomes", {}) if resume else {}
    completed_keys = set(outcomes)
    progress = dict(mode="live" if live else "backfill", start=start.isoformat(), end=end.isoformat(),
                    checkpoint_version=1, completed_keys=sorted(completed_keys),
                    outcomes=outcomes,
                    total=None, processed=len(completed_keys), stored=previous.get("stored", 0) if resume else 0,
                    api_page_cache=previous.get("api_page_cache", {}) if resume else {},
                    suspended_windows=suspended,
                    updated_at=timezone.now().isoformat())
    job_query = CollectionJob.objects.using(alias).filter(pk=job.pk, generation=job.generation)
    def save_progress(**extra):
        if not job_query.update(progress=progress, **{lane: progress}, **extra):
            raise G2BError("CONDITION_CHANGED", "수집조건이 변경되어 다음 작업에서 이어갑니다.")
    save_progress(status="running", error_code="", **({"requested": False} if live else {"backfill_status": "BACKFILL_RUNNING"}))
    if isinstance(client, Client):
        client.bind_checkpoint(progress, save_progress)
        client.scope_check = check_scope if not live else None
    try:
        rows = client.search(job.rule, start, end)
        selected = {(r.get("bidNtceNo"), canonical_order(r.get("bidNtceOrd"))): r for r in rows}
        # Old notices can change outside the posting-date search window.
        changes = client.changes(start, end) if live else []
        for row in changes:
            selected[(row.get("bidNtceNo"), canonical_order(row.get("bidNtceOrd")))] = row
        search_keys = {(r.get("bidNtceNo"), canonical_order(r.get("bidNtceOrd"))) for r in rows}
        progress.update(total=len(selected), updated_at=timezone.now().isoformat())
        progress.update(search_received=len(rows), changes_received=len(changes),
                        search_unique=len(search_keys), search_duplicates=len(rows)-len(search_keys),
                        merged_duplicates=len(rows)+len(changes)-len(selected))
        save_progress()
        active_hashes = []
        for key, row in selected.items():
            check_scope()
            if not key[0]:
                raise G2BError("MISSING_NOTICE_KEY", "공고 식별자가 없습니다.")
            # Include source content so a notice changed during a retry is rechecked.
            import hashlib
            checkpoint_key = hashlib.sha256(json.dumps(row, sort_keys=True, ensure_ascii=False).encode()).hexdigest()
            active_hashes.append(checkpoint_key)
            if checkpoint_key in completed_keys:
                continue
            if not CollectionRule.objects.using(alias).filter(pk=job.rule_id, active=True).exists():
                raise G2BError("PAUSED", "비활성 조건의 수집을 중단했습니다.")
            existing = Notice.objects.using(alias).filter(number=key[0], order=key[1]).first()
            if existing and existing.raw.get("notice") == row:
                details = {name: existing.raw.get(name, []) for name in ("regions", "industries", "products")}
            else:
                details = client.details(row)
            known = Notice.objects.using(alias).filter(number=key[0], order=key[1], rules=job.rule).exists()
            selected_by_industry = job.rule.kind == "industry" and key in search_keys
            with transaction.atomic(using=alias):
                outcome = "rejected"
                if selected_by_industry or known or rule_matches(job.rule, row, details):
                    outcome = store_notice(row, details, job.rule, now) or "expired"
                if outcome in {"inserted", "updated", "unchanged"}:
                    progress["stored"] += 1
                outcomes[checkpoint_key] = dict(outcome=outcome, number=key[0], order=key[1])
                progress["processed"] += 1
                completed_keys.add(checkpoint_key)
                progress["completed_keys"] = sorted(completed_keys)
                progress["updated_at"] = timezone.now().isoformat()
                save_progress()
        metrics = {kind: sum(outcomes[h]["outcome"] == kind for h in active_hashes)
                   for kind in ("inserted", "updated", "unchanged", "rejected", "expired")}
        matched = metrics["inserted"] + metrics["updated"] + metrics["unchanged"]
        for h in active_hashes:
            item = outcomes[h]
            if item["outcome"] in {"inserted", "updated", "unchanged"} and not Notice.objects.using(alias).filter(
                    number=item["number"], order=item["order"], rules=job.rule).exists():
                raise G2BError("MATCH_COUNT_MISMATCH", "저장된 조건 연결을 확인할 수 없습니다.")
        if sum(metrics.values()) != len(selected):
            raise G2BError("COUNT_MISMATCH", "수신 고유 공고와 처리 수량이 일치하지 않습니다.")
        metrics.update(received=len(rows), unique=len(search_keys), duplicates=len(rows)-len(search_keys),
                       candidate_unique=len(selected), matched=matched, changes_received=len(changes))
        progress.update(metrics=metrics, finished=True, stored=matched, processed=len(selected))
        progress.pop("completed_keys", None)
        progress.pop("outcomes", None)
        progress["api_queries"] = [dict(operation=q["operation"], query=q["query"], numOfRows=q["numOfRows"],
                                       totalCount=q["totalCount"], complete=q["complete"],
                                       received=sum(p["received"] for p in q["pages"]),
                                       pages=[dict(pageNo=p["pageNo"], received=p["received"]) for p in q["pages"]])
                                   for q in progress.pop("api_page_cache", {}).values()
                                   if q["operation"] in {"getBidPblancListInfoServcPPSSrch", "getBidPblancListInfoServc"}]
        metrics["api_queries"] = progress["api_queries"]
        source_queries = [q for q in progress["api_queries"] if q["operation"] == "getBidPblancListInfoServcPPSSrch"]
        if isinstance(client, Client) and (len(source_queries) != 1 or not source_queries[0]["complete"] or
                                           source_queries[0]["totalCount"] != len(rows)):
            raise G2BError("SOURCE_COUNT_MISMATCH", "API 전체 건수와 수신 건수가 일치하지 않습니다.")
        metrics["source_total"] = source_queries[0]["totalCount"] if source_queries else None
        updates = dict(status="success", error_code="", last_success_at=now, fetched_count=len(selected))
        if live:
            updates.update(live_cursor=end, last_incremental_success=now,
                           due_at=now if end < now else now + timedelta(hours=1))
        else:
            updates.update(backfill_cursor=max(job.backfill_cursor, end), backfill_status="BACKFILL_PENDING")
        with transaction.atomic(using=alias):
            check_scope()
            CollectionWindow.objects.using(alias).update_or_create(
                job=job, generation=job.generation, mode="live" if live else "backfill", start=start, end=end,
                defaults=dict(metrics=metrics, verified=True, completed_at=now))
            save_progress(**updates)
            if not live:
                from .lifecycle import coverage_gap
                job.refresh_from_db(using=alias)
                if coverage_gap(job, now) is None:
                    job_query.update(backfill_status="BACKFILL_COMPLETE")
                elif recent_backfill_window(job, now) is None:
                    job_query.update(backfill_status="RANGE_COMPLETE")
        return True
    except Exception as exc:
        code = exc.code if isinstance(exc, G2BError) else "COLLECTION_ERROR"
        saved = job_query.values_list(lane, flat=True).first() or {}
        saved["last_error"] = code
        job_query.update(status="failed", error_code=code, progress=saved, **{lane: saved}, **({} if live else {
            "backfill_status": "PAUSED" if code in {"PAUSED", "SCOPE_CHANGED", "BUDGET_EXHAUSTED", "TIME_BUDGET_EXHAUSTED", "DAILY_BUDGET_EXHAUSTED"} else "BACKFILL_FAILED"}))
        raise


def run_worker(budget=100, max_steps=10):
    import time
    from .lifecycle import match_existing
    with worker_lock() as acquired:
        if not acquired:
            return 0
        jobs = CollectionJob.objects.using(central_alias()).filter(rule__active=True).select_related("rule").order_by("due_at", "id")
        completed = 0
        live_allowance = max(1, budget // 2)
        remaining = budget
        deadline = time.monotonic() + max(60, min(840, getattr(settings, "G2B_JOB_TIME_BUDGET_SECONDS", 720)))
        next_request_at = 0
        for mode in ("live", "backfill"):
            client = Client(budget=min(remaining, live_allowance) if mode == "live" else remaining)
            client.deadline = deadline
            client.next_request_at = next_request_at
            initial_budget = client.budget
            for _ in range(max_steps):
                progress = False
                lane = "incremental_progress" if mode == "live" else "backfill_progress"
                pending = sorted(jobs.all(), key=lambda job: (getattr(job, lane).get("updated_at", ""), str(job.pk)))
                turn_budget = max(1, min(100, client.budget // max(1, len(pending))))
                for job in pending:
                    now = minute(timezone.now())
                    if completed >= max_steps or client.budget <= 0:
                        break
                    if mode == "live" and not (job.requested or job.due_at <= now):
                        continue
                    if mode == "backfill":
                        used = ApiBudget.objects.using(central_alias()).filter(day=now.date()).values_list("used", flat=True).first() or 0
                        daily = getattr(settings, "G2B_CENTRAL_DAILY_BUDGET", 500)
                        reserve = max(0, min(getattr(settings, "G2B_INCREMENTAL_REQUEST_RESERVE", 100), daily // 2))
                        if daily - used <= reserve:
                            return completed
                        client.budget = min(client.budget, daily - used - reserve)
                    if not match_existing(job, now):
                        progress = True
                        continue
                    phase_budget = client.budget
                    allowance = min(phase_budget, turn_budget)
                    client.budget = allowance
                    try:
                        changed = run_step(job, client, now, mode=mode)
                        completed += int(changed)
                        progress |= changed
                    except G2BError as exc:
                        if exc.code in {"DAILY_BUDGET_EXHAUSTED", "API_20", "API_22", "API_23", "API_29",
                                        "API_30", "API_31", "MISSING_SERVICE_KEY", "NETWORK_ERROR", "TIME_BUDGET_EXHAUSTED", "SCOPE_CHANGED"}:
                            return completed
                        if exc.code == "BUDGET_EXHAUSTED":
                            progress = True
                    finally:
                        client.budget = phase_budget - (allowance - client.budget)
                if not progress or client.budget <= 0 or completed >= max_steps:
                    break
            remaining -= initial_budget - client.budget
            next_request_at = client.next_request_at
        return completed
