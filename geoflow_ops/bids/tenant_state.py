"""Tenant-shared bookmarks and reversible hiding. Actor identity validates requests only."""
from uuid import UUID

from django.core.exceptions import PermissionDenied
from django.db import connections, transaction
from control.services_identity import lookup_user_id_from_request
from procurement.service import central_alias


def user_id(request):
    value = lookup_user_id_from_request(request)
    if not value:
        raise PermissionDenied("사용자 식별정보를 확인할 수 없습니다.")
    return str(UUID(str(value)))


def _scope(alias, actor, origin):
    if not alias or alias == central_alias() or origin not in {"central", "legacy"}:
        raise ValueError("회사와 공고 출처를 확인하세요.")
    return str(UUID(str(actor)))


def rows(alias, actor, origin):
    _scope(alias, actor, origin)
    with connections[alias].cursor() as cur:
        cur.execute("SELECT notice_id,saved,hidden FROM bid.tenant_state WHERE origin=%s",
                    [origin])
        return {str(pk): {"saved": saved, "hidden": hidden} for pk, saved, hidden in cur.fetchall()}


def save(alias, actor, origin, notice_ids, action):
    _scope(alias, actor, origin)
    actions = {"save": ("saved", True), "unsave": ("saved", False),
               "hide": ("hidden", True), "restore": ("hidden", False)}
    return _save(alias, actor, origin, notice_ids, action, actions)


def save_progress(alias, actor, origin, notice_id, action):
    from django.utils import timezone
    now = timezone.now()
    return _save(alias, actor, origin, [notice_id], action, {
        'register': ('registered_at', now), 'unregister': ('registered_at', None),
        'submit': ('submitted_at', now), 'unsubmit': ('submitted_at', None),
    })


def _save(alias, actor, origin, notice_ids, action, actions):
    _scope(alias, actor, origin)
    if action not in actions or not 1 <= len(notice_ids) <= 30:
        raise ValueError("최대 30개 공고와 작업을 선택하세요.")
    try:
        ids = sorted({str(UUID(str(pk))) for pk in notice_ids})
    except (ValueError, TypeError, AttributeError):
        raise ValueError("공고 식별정보를 확인하세요.")
    if origin == "central":
        from procurement.models import Notice
        found = {str(pk) for pk in Notice.objects.using(central_alias()).filter(pk__in=ids).values_list("pk", flat=True)}
    else:
        with connections[alias].cursor() as cur:
            cur.execute("SELECT id FROM bid.notices WHERE id IN (" + ",".join(["%s"] * len(ids)) + ")", ids)
            found = {str(row[0]) for row in cur.fetchall()}
    if found != set(ids):
        raise ValueError("공고를 찾을 수 없습니다. 목록을 새로고침하세요.")
    column, value = actions[action]
    with transaction.atomic(using=alias), connections[alias].cursor() as cur:
        for pk in ids:
            # Column comes only from the fixed action mapping above. The tenant DB
            # owns the state; preserve the independent saved/hidden flag.
            cur.execute(f"""INSERT INTO bid.tenant_state(origin,notice_id,{column})
                VALUES (%s,%s,%s) ON CONFLICT(origin,notice_id)
                DO UPDATE SET {column}=excluded.{column},updated_at=CURRENT_TIMESTAMP""", [origin, pk, value])
    return ids


def refresh_personal_snapshot(cur):
    """Deployment only: reconcile newer legacy writes after a failed cutover.

    Caller must drain legacy workers and confirm the previous code used personal
    state. Preserve newer shared rows; never run during normal shared-state use.
    """
    cur.execute("""INSERT INTO bid.tenant_state(origin,notice_id,saved,hidden,updated_at)
        SELECT origin,notice_id,bool_or(saved),bool_and(hidden),max(updated_at)
        FROM bid.personal_state GROUP BY origin,notice_id
        ON CONFLICT(origin,notice_id) DO UPDATE
        SET saved=excluded.saved,hidden=excluded.hidden,updated_at=excluded.updated_at
        WHERE excluded.updated_at > bid.tenant_state.updated_at""")


def progress_rows(alias, actor, origin, notice_ids):
    _scope(alias, actor, origin)
    ids = [str(UUID(str(pk))) for pk in notice_ids]
    if not ids:
        return {}
    with connections[alias].cursor() as cur:
        cur.execute("SELECT notice_id,registered_at,submitted_at FROM bid.tenant_state WHERE origin=%s AND notice_id IN (" + ",".join(["%s"] * len(ids)) + ")", [origin, *ids])
        return {str(pk): dict(registered_at=registered, submitted_at=submitted,
            progress_badge='투찰' if submitted else ('참가' if registered else ''))
            for pk, registered, submitted in cur.fetchall()}


def apply_progress(notice, progress):
    notice.update(progress)
    for event in notice.get('timeline', []):
        if event['key'] in {'registration_close_at', 'bid_close_at'}:
            registered = event['key'] == 'registration_close_at'
            done = progress.get('registered_at' if registered else 'submitted_at')
            event.update(completed_at=done,
                action=('unregister' if done else 'register') if registered else ('unsubmit' if done else 'submit'),
                action_label='취소' if done else '완료',
                action_title=('참가등록' if registered else '투찰') + (' 완료 취소' if done else ' 완료'))
    return notice
