"""Stable user conditions and explicit provider mappings, owned by central DB."""
from uuid import UUID, NAMESPACE_URL, uuid5

from django.db.models import Q

from geoflow_ops.bids.matcher import normalized
from .models import CollectionRule, InterestCondition
from .service import central_alias

def configured_industries():
    import json
    from pathlib import Path
    mappings = {}
    for path in sorted((Path(__file__).resolve().parent.parent / 'deploy' / 'bids').glob('*rules.json')):
        for row in json.loads(path.read_text(encoding='utf-8')):
            if row['kind'] == 'industry' and row.get('condition_key'):
                mappings[(row.get('source', 'g2b'), row['value'])] = (row['condition_key'], row['name'])
    return mappings


def condition_id(kind, key):
    return uuid5(NAMESPACE_URL, f'geoflow:bid-interest:{kind}:{key}')


def identity(rule):
    if rule.kind == 'keyword':
        term = normalized(rule.value)
        return 'keyword-' + uuid5(NAMESPACE_URL, term).hex, rule.value.strip()
    return configured_industries().get((rule.source, rule.value), ('legacy-' + rule.pk.hex, rule.name))


def bind_rule(rule, *, key=None, name=None):
    """Attach explicitly seeded or legacy rules without changing collection semantics."""
    if rule.condition_id:
        if rule.condition.kind != rule.kind:
            raise ValueError('관심조건과 수집규칙의 종류가 다릅니다.')
        if key and rule.condition.key != key:
            raise ValueError("이미 연결된 관심조건을 임의로 변경할 수 없습니다.")
        return rule.condition
    default_key, default_name = identity(rule)
    key, name = key or default_key, name or default_name
    alias = central_alias()
    condition, _ = InterestCondition.objects.using(alias).get_or_create(
        kind=rule.kind, key=key,
        defaults={'id': condition_id(rule.kind, key), 'name': name, 'active': rule.active},
    )
    CollectionRule.objects.using(alias).filter(pk=rule.pk, condition__isnull=True).update(condition=condition)
    rule.refresh_from_db(using=alias, fields=['condition'])
    if rule.condition.kind != rule.kind:
        raise ValueError('관심조건과 수집규칙의 종류가 다릅니다.')
    return rule.condition


def canonical_ids(values, *, strict=False):
    """Read legacy provider UUIDs and current logical UUIDs, without tenant writes."""
    ids = {str(UUID(str(value))) for value in values}
    alias = central_alias()
    direct = set(str(pk) for pk in InterestCondition.objects.using(alias).filter(pk__in=ids).values_list('pk', flat=True))
    rules = CollectionRule.objects.using(alias).filter(pk__in=ids - direct)
    mapped, known = set(), set(direct)
    for rule in rules:
        known.add(str(rule.pk))
        if rule.condition_id:
            mapped.add(str(rule.condition_id))
        elif strict:
            raise ValueError('논리 관심조건이 연결되지 않은 수집규칙이 있습니다.')
        else:
            mapped.add(str(rule.pk))
    if strict and ids - known:
        raise ValueError('확인할 수 없는 기존 관심조건이 있습니다. 원본 설정을 보존했습니다.')
    return sorted(direct | mapped)


def resolve_rule_ids(values):
    ids = canonical_ids(values)
    # Include legacy unmapped references while an existing tenant is read before conversion.
    return [str(pk) for pk in CollectionRule.objects.using(central_alias()).filter(
        Q(condition_id__in=ids) | Q(pk__in=ids, condition__isnull=True)
    ).values_list('pk', flat=True)]
