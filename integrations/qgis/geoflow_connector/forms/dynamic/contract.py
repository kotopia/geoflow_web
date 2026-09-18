# 제목: Dynamic Form 중앙 계약 정규화
# 기능: v3 정의의 필드·규칙·저장소 형식을 검증하고 레이어별 순서를 확정
"""Fail-closed normalization for the central Final Form Definition v3."""
from __future__ import annotations

from copy import deepcopy


SUPPORTED_VERSION = "gis-final-form-v3"
WIDGET_TYPES = {
    "text", "multiline", "integer", "decimal", "combo", "boolean",
    "date", "datetime", "photo", "relation", "hidden",
}
SEMANTIC_TYPES = {
    "text", "integer", "decimal", "boolean", "date", "datetime",
    "photo", "relation",
}
STORAGE_KINDS = {"column", "ext_data", "ops.attachments", "relation"}


class DefinitionContractError(ValueError):
    pass


def _text(value) -> str:
    return str(value or "").strip()


def normalize_definition(payload: dict) -> dict:
    """Validate the one central contract; never synthesize a tenant fallback."""
    if not isinstance(payload, dict) or payload.get("ok") is False:
        raise DefinitionContractError("중앙 Final Form Definition 응답이 올바르지 않습니다.")
    if _text(payload.get("version")) != SUPPORTED_VERSION:
        raise DefinitionContractError("지원하지 않는 Final Form Definition 버전입니다.")
    if not _text(payload.get("revision")):
        raise DefinitionContractError("Final Form Definition revision이 없습니다.")
    raw_fields = payload.get("fields")
    raw_rules = payload.get("rules", [])
    if not isinstance(raw_fields, list) or not isinstance(raw_rules, list):
        raise DefinitionContractError("Final Form Definition 필드 또는 규칙이 올바르지 않습니다.")

    fields = []
    ids = set()
    for raw in raw_fields:
        if not isinstance(raw, dict):
            raise DefinitionContractError("Final Form Definition 필드가 객체가 아닙니다.")
        row = deepcopy(raw)
        field_id = _text(row.get("id"))
        standard = _text(row.get("layer_standard_name")).upper()
        semantic = _text(row.get("semantic_data_type") or "text").casefold()
        widget = _text(row.get("widget_type") or semantic or "text").casefold()
        storage = row.get("storage") or {}
        if not field_id or field_id in ids or not standard:
            raise DefinitionContractError("Final Form Definition 필드 식별자가 없거나 중복됩니다.")
        if semantic not in SEMANTIC_TYPES or widget not in WIDGET_TYPES:
            raise DefinitionContractError(f"지원하지 않는 중앙 필드 유형입니다: {field_id}")
        if not isinstance(storage, dict) or storage.get("kind") not in STORAGE_KINDS:
            raise DefinitionContractError(f"중앙 필드 저장 계약이 올바르지 않습니다: {field_id}")
        if storage["kind"] in {"column", "ext_data"} and not _text(storage.get("key")):
            raise DefinitionContractError(f"중앙 필드 저장 키가 없습니다: {field_id}")
        codes = row.get("reference_codes", [])
        if not isinstance(codes, list):
            raise DefinitionContractError(f"중앙 참조코드가 올바르지 않습니다: {field_id}")
        normalized_codes = []
        code_ids = set()
        for code in codes:
            if not isinstance(code, dict) or not _text(code.get("id")):
                raise DefinitionContractError(f"중앙 참조코드 식별자가 없습니다: {field_id}")
            if _text(code["id"]) in code_ids:
                raise DefinitionContractError(f"중앙 참조코드가 중복됩니다: {field_id}")
            code_ids.add(_text(code["id"]))
            if code.get("enabled", True):
                normalized_codes.append({
                    "id": _text(code["id"]), "value": str(code.get("value") or ""),
                    "label": _text(code.get("label") or code.get("value")),
                    "order": int(code.get("order") or 0), "enabled": True,
                })
        normalized_codes.sort(key=lambda item: (item["order"], item["label"], item["id"]))
        row.update({
            "id": field_id, "layer_standard_name": standard,
            "semantic_data_type": semantic, "widget_type": widget,
            "label": _text(row.get("label") or row.get("field_name") or row.get("field_identifier")),
            "visible": bool(row.get("visible", True)), "required": bool(row.get("required", False)),
            "readonly": bool(row.get("readonly", False)),
            "display_order": int(row.get("display_order") or 0),
            "layout": row.get("layout") if isinstance(row.get("layout"), dict) else {},
            "reference_codes": normalized_codes, "storage": deepcopy(storage),
        })
        ids.add(field_id)
        fields.append(row)

    rules = []
    for raw in raw_rules:
        if not isinstance(raw, dict):
            raise DefinitionContractError("중앙 연결 규칙이 객체가 아닙니다.")
        source = _text(raw.get("source_field_id"))
        target = _text(raw.get("target_field_id"))
        source_code = _text(raw.get("source_code_id"))
        allowed = raw.get("allowed_code_ids")
        if source not in ids or target not in ids or not source_code or not isinstance(allowed, list):
            raise DefinitionContractError("중앙 연결 규칙이 존재하지 않는 필드를 참조합니다.")
        rules.append({"id": _text(raw.get("id")), "source_field_id": source,
                      "source_code_id": source_code, "target_field_id": target,
                      "allowed_code_ids": [_text(value) for value in allowed]})

    fields.sort(key=lambda row: (row["layer_standard_name"], row["display_order"], row["label"], row["id"]))
    return {"ok": True, "version": SUPPORTED_VERSION, "revision": _text(payload["revision"]),
            "group": deepcopy(payload.get("group")), "fields": fields, "rules": rules,
            "components": deepcopy(payload.get("components") or [])}


def layer_fields(definition: dict, standard_name: str) -> list[dict]:
    standard = _text(standard_name).upper()
    return [row for row in definition.get("fields", [])
            if row.get("layer_standard_name") == standard]
