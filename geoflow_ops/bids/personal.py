"""Tenant-owned, central-user scoped bookmarks and reversible hiding."""
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
    actor = _scope(alias, actor, origin)
    with connections[alias].cursor() as cur:
        cur.execute("SELECT notice_id,saved,hidden FROM bid.personal_state WHERE user_id=%s AND origin=%s",
                    [actor, origin])
        return {str(pk): {"saved": saved, "hidden": hidden} for pk, saved, hidden in cur.fetchall()}


def save(alias, actor, origin, notice_ids, action):
    actor = _scope(alias, actor, origin)
    actions = {"save": ("saved", True), "unsave": ("saved", False),
               "hide": ("hidden", True), "restore": ("hidden", False)}
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
            # Column comes only from the fixed action mapping above. Neither another
            # user's state nor the independent saved/hidden flag is overwritten.
            cur.execute(f"""INSERT INTO bid.personal_state(user_id,origin,notice_id,{column})
                VALUES (%s,%s,%s,%s) ON CONFLICT(user_id,origin,notice_id)
                DO UPDATE SET {column}=excluded.{column},updated_at=CURRENT_TIMESTAMP""", [actor, origin, pk, value])
    return ids
