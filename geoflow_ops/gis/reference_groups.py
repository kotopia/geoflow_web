"""One applicability rule for central codes and project-scoped final definitions."""
from .form_definitions import DefinitionError


def scope_layers(data, scopes):
    result = {}
    for scope in scopes:
        l2 = scope.get('2')
        if not l2 or ('catalogs' in data and l2 not in {row['id'] for row in data['catalogs']}):
            continue
        keys = {(str(level), value) for level, value in scope.items() if value}
        result.setdefault(l2, set()).update(
            row['layer_id'] for row in data['layer_catalogs']
            if (str(row['catalog_level']), row['catalog_item_id']) in keys)
    return {key: sorted(value) for key, value in sorted(result.items())}


def layer_group_ids(data, config, layer_id):
    assignments = config.get('reference_groups', {})
    known = {row['id'] for row in data.get('groups', [])}
    if any(group not in known for values in assignments.values() for group in values):
        raise DefinitionError('GIS 적용그룹이 삭제되었거나 유효하지 않습니다. 설정을 확인하세요.')
    return {group for l2, layers in config.get('reference_scope_layers', {}).items()
            if layer_id in layers for group in assignments.get(l2, [])}


def codes_for_field(data, field_id, group_ids=()):
    by_code = {}
    for link in data.get('code_groups', []):
        by_code.setdefault(link['code_id'], set()).add(link['group_id'])
    active = set(group_ids)
    return [row for row in data['codes'] if row['field_id'] == field_id
            and (not by_code.get(row['id']) or by_code[row['id']] & active)]


def selected_group_ids(data):
    values = data.getlist('reference_groups') if hasattr(data, 'getlist') else data.get('reference_groups', [])
    if not isinstance(values, list):
        raise DefinitionError('적용그룹은 목록으로 선택하세요.')
    from .form_definitions import identifier
    return sorted({identifier(value) for value in values})
