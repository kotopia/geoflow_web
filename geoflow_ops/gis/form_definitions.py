"""Shared validation helpers for GIS definitions."""
from uuid import UUID

class DefinitionError(ValueError):
    pass

def rows(cur, sql, params=()):
    cur.execute(sql, params)
    keys = [c[0] for c in cur.description]
    return [dict(zip(keys, r)) for r in cur.fetchall()]


def identifier(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise DefinitionError("식별자가 올바르지 않습니다.") from None


def text(value, maximum=120):
    value = str(value or "").strip()
    if not value or len(value) > maximum:
        raise DefinitionError("이름 또는 코드의 길이를 확인하세요.")
    return value
