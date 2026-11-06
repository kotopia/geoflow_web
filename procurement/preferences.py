"""Tenant-owned logical selections; provider UUIDs remain readable during conversion."""
import json
from uuid import UUID

from django.db import connections, transaction

from geoflow_ops.bids.repository import load_filters
from .models import CollectionRule, InterestCondition
from .conditions import bind_rule, canonical_ids, resolve_rule_ids
from .service import central_alias, enabled


def choices(alias):
    if not enabled(alias):
        raise ValueError("중앙 조회가 활성화된 회사에서만 설정할 수 있습니다.")
    return list(InterestCondition.objects.using(central_alias()).order_by("kind", "name", "pk"))


def stored_ids(alias, filters=None):
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
        active=True, source="g2b", kind="industry", value__in=codes).values_list("pk", flat=True)]


def selected_conditions(alias, filters=None):
    return canonical_ids(stored_ids(alias, filters))


def selected_ids(alias, filters=None):
    # Existing list/count callers consume resolved source rules, never UI selections.
    return resolve_rule_ids(stored_ids(alias, filters))


def save(alias, values):
    available = {str(rule.pk): rule for rule in choices(alias)}
    try:
        selected = {str(UUID(str(value))) for value in values}
    except (ValueError, TypeError, AttributeError):
        raise ValueError("수집조건을 다시 선택하세요.")
    if not selected <= available.keys():
        raise ValueError("존재하지 않는 중앙 수집조건입니다.")
    previous = set(selected_conditions(alias))
    if any(not available[value].active for value in selected - previous):
        raise ValueError("중앙에서 비활성화된 조건은 새로 선택할 수 없습니다.")
    with transaction.atomic(using=alias), connections[alias].cursor() as cur:
        cur.execute("""INSERT INTO bid.central_preferences(id,rule_ids) VALUES (1,%s::jsonb)
          ON CONFLICT(id) DO UPDATE SET rule_ids=excluded.rule_ids,updated_at=now()""",
                    [json.dumps(sorted(selected))])


def add_keyword(alias, keyword):
    """Add one logical keyword and bind the configured central keyword sources."""
    from django.conf import settings
    from .models import SOURCES
    from .service import enqueue_rule
    sources = getattr(settings, 'PROCUREMENT_KEYWORD_SOURCES', tuple(key for key, _ in SOURCES))
    term = str(keyword or '').strip()
    if not 2 <= len(term) <= 120:
        raise ValueError('수집 키워드는 2~120자로 입력하세요.')
    term = term.upper() if term.isascii() else term
    # Validate tenant before any central mutation. Shared rule/job creation is
    # idempotent; if tenant preference save fails, retry attaches the same rule.
    choices(alias)
    with transaction.atomic(using=central_alias()):
        existing = CollectionRule.objects.using(central_alias()).filter(kind='keyword', value__iexact=term)
        if existing.exists() and not existing.filter(active=True).exists():
            raise ValueError('중앙에서 중지한 키워드입니다. 중앙 관리자에게 활성화를 요청하세요.')
        from .conditions import condition_id, identity
        candidate = CollectionRule(kind='keyword', value=term)
        key, name = identity(candidate)
        condition, _ = InterestCondition.objects.using(central_alias()).get_or_create(
            kind='keyword', key=key, defaults={'id': condition_id('keyword', key), 'name': name})
        if not condition.active:
            raise ValueError('중앙에서 중지한 키워드입니다. 중앙 관리자에게 활성화를 요청하세요.')
        for source in sources:
            rule = CollectionRule.objects.using(central_alias()).filter(
                source=source, kind='keyword', value__iexact=term).first()
            if rule is None:
                rule, _ = CollectionRule.objects.using(central_alias()).get_or_create(
                    source=source, kind='keyword', value=term,
                    defaults={'name': term, 'condition': condition})
            bound = bind_rule(rule)
            if bound.pk != condition.pk:
                raise ValueError('기존 키워드 연결이 다릅니다. 중앙 관리자의 확인이 필요합니다.')
            if rule.active:
                enqueue_rule(rule)
    values = set(selected_conditions(alias))
    values.add(str(condition.pk))
    save(alias, values)
