"""Versioned saved SearchBuilder schema; no expressions are executed as SQL."""
import json
from datetime import date
from decimal import Decimal, InvalidOperation

# Matches result columns (checkbox=0). Labels are public aliases, not SQL names.
FIELDS = {
    'code': ('계약번호', 'string'), 'name': ('계약명', 'string'),
    'status': ('상태', 'string'), 'start': ('시작일', 'date'),
    'end': ('종료일', 'date'), 'kind': ('계약종류', 'string'),
    'amount': ('계약금액', 'num'), 'client': ('거래처', 'string'),
    'orgunit': ('계약자', 'string'), 'events': ('표시 중인 이벤트', 'string'),
}
OPERATORS = {
    'string': {'=', '!=', 'contains', '!contains', 'starts', '!starts', 'ends', '!ends', 'null', '!null'},
    'num': {'=', '!=', '<', '<=', '>', '>=', 'between', '!between', 'null', '!null'},
    'date': {'=', '!=', '<', '>', 'between', '!between', 'null', '!null'},
}


def validate_definition(value):
    if not isinstance(value, dict) or value.get('version') != 1:
        raise ValueError('지원하지 않는 필터 형식입니다.')
    if len(json.dumps(value, ensure_ascii=False)) > 24000:
        raise ValueError('필터가 너무 큽니다.')
    count = 0

    def group(node, depth=0):
        nonlocal count
        if not isinstance(node, dict) or depth > 4:
            raise ValueError('조건 그룹은 최대 4단계입니다.')
        criteria = node.get('criteria', [])
        if not isinstance(criteria, list) or node.get('logic', 'AND') not in {'AND', 'OR'}:
            raise ValueError('잘못된 조건 그룹입니다.')
        out = []
        for item in criteria:
            if not isinstance(item, dict):
                raise ValueError('잘못된 조건입니다.')
            if 'criteria' in item:
                out.append(group(item, depth + 1))
                continue
            count += 1
            field = item.get('origData')
            if count > 30 or field not in FIELDS:
                raise ValueError('지원하지 않는 필터 항목입니다.')
            label, kind = FIELDS[field]
            op = item.get('condition')
            vals = item.get('value', [])
            if op not in OPERATORS[kind] or not isinstance(vals, list):
                raise ValueError('지원하지 않는 연산자입니다.')
            expected = 0 if op in {'null', '!null'} else 2 if op in {'between', '!between'} else 1
            if len(vals) != expected or any(not isinstance(v, (str, int, float)) or len(str(v)) > 200 for v in vals):
                raise ValueError('조건값을 확인하세요.')
            for val in vals:
                try:
                    if kind == 'num':
                        number = Decimal(str(val))
                        if not number.is_finite() or abs(number) >= Decimal('1e15'):
                            raise ValueError
                    elif kind == 'date':
                        date.fromisoformat(str(val))
                except (ValueError, InvalidOperation):
                    raise ValueError('숫자 또는 날짜 조건값을 확인하세요.')
            out.append({'data': label, 'origData': field, 'type': kind, 'condition': op, 'value': vals})
        return {'logic': node.get('logic', 'AND'), 'criteria': out}

    tree = group(value.get('conditions', {}))
    order = value.get('order', [[1, 'desc']])
    if not isinstance(order, list) or len(order) > 10:
        raise ValueError('정렬을 확인하세요.')
    for item in order:
        if not isinstance(item, list) or len(item) != 2 or type(item[0]) is not int or not 1 <= item[0] <= 10 or item[1] not in {'asc', 'desc'}:
            raise ValueError('정렬을 확인하세요.')
    return {'version': 1, 'conditions': tree, 'order': order}
