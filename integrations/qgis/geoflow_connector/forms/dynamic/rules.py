# 제목: Dynamic Form 중앙 규칙 실행기
# 기능: 코드 연결 규칙과 필수값 검증을 업무별 하드코딩 없이 실행
"""Central rule evaluation; this module contains no business-specific values."""
from __future__ import annotations

from .boolean_codes import boolean_code_values, canonical_boolean_code


def code_id(field: dict, value):
    value = canonical_boolean_code(field, value)
    if value in (None, ""):
        return None
    return next((row["id"] for row in field.get("reference_codes", [])
                 if str(row.get("value")) == str(value)), None)


def allowed_code_ids(definition: dict, target_id: str, values: dict) -> set[str] | None:
    fields = {row["id"]: row for row in definition.get("fields", [])}
    matched = []
    for rule in definition.get("rules", []):
        if rule["target_field_id"] != target_id:
            continue
        source = fields.get(rule["source_field_id"])
        if source and code_id(source, values.get(source["id"])) == rule["source_code_id"]:
            matched.append(set(rule["allowed_code_ids"]))
    if not matched:
        return None
    allowed = matched[0]
    for values_set in matched[1:]:
        allowed &= values_set
    return allowed


def validate(definition: dict, fields: list[dict], values: dict) -> list[str]:
    errors = []
    for field in fields:
        value = canonical_boolean_code(field, values.get(field["id"]))
        if field.get("visible") and field.get("required") and value in (None, ""):
            errors.append(field["label"] + " 필드는 필수입니다.")
        codes = field.get("reference_codes", [])
        kind = str(
            field.get("widget_type") or field.get("semantic_data_type") or ""
        ).casefold()
        code_domain = bool(codes) and not (
            kind == "boolean" and boolean_code_values(field) is None
        )
        if code_domain and value not in (None, "") and code_id(field, value) is None:
            errors.append(field["label"] + " 코드값이 중앙 정의와 일치하지 않습니다.")
        allowed = allowed_code_ids(definition, field["id"], values) if code_domain else None
        selected = code_id(field, value)
        if allowed is not None and value not in (None, "") and selected not in allowed:
            errors.append(field["label"] + " 값이 연결 규칙에서 허용되지 않습니다.")
    return errors
