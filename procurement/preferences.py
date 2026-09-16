"""Company-owned selections; central rule identifiers are references, not copied rules."""
import json
from uuid import UUID

from django.db import connections, transaction

from geoflow_ops.bids.repository import load_filters
from .models import CollectionRule
from .service import central_alias, enabled


def choices(alias):
    if not enabled(alias):
        raise ValueError("중앙 조회가 활성화된 회사에서만 설정할 수 있습니다.")
    return list(CollectionRule.objects.using(central_alias()).order_by("kind", "name"))


def selected_ids(alias, filters=None):
    with connections[alias].cursor() as cur:
        cur.execute("SELECT rule_ids FROM bid.central_preferences WHERE id=1")
        row = cur.fetchone()
    if row:
        return json.loads(row[0]) if isinstance(row[0], str) else row[0]
    # First cutover preserves existing active industry choices. Nothing selected
    # remains empty: never silently subscribe a company to every central rule.
    filters = filters if filters is not None else load_filters(alias)
    codes = [item["code"] for item in filters.get("industry", [])]
    return [str(pk) for pk in CollectionRule.objects.using(central_alias()).filter(
        active=True, kind="industry", value__in=codes).values_list("pk", flat=True)]


def save(alias, values):
    available = {str(rule.pk): rule for rule in choices(alias)}
    try:
        selected = {str(UUID(str(value))) for value in values}
    except (ValueError, TypeError, AttributeError):
        raise ValueError("수집조건을 다시 선택하세요.")
    if not selected <= available.keys():
        raise ValueError("존재하지 않는 중앙 수집조건입니다.")
    previous = set(selected_ids(alias))
    if any(not available[value].active for value in selected - previous):
        raise ValueError("중앙에서 비활성화된 조건은 새로 선택할 수 없습니다.")
    with transaction.atomic(using=alias), connections[alias].cursor() as cur:
        cur.execute("""INSERT INTO bid.central_preferences(id,rule_ids) VALUES (1,%s::jsonb)
          ON CONFLICT(id) DO UPDATE SET rule_ids=excluded.rule_ids,updated_at=now()""",
                    [json.dumps(sorted(selected))])
