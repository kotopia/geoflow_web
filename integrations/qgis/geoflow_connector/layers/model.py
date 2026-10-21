# 제목: layers/model.py
# 기능: 레이어 그룹·검색·표시명과 필드 편집기 설정의 순수 변환
from __future__ import annotations

# ============================================================
# 레이어 목록·검색·도메인 그룹 순수 변환
# ============================================================
def workspace_rows(definitions, layers):
    """Rows are keyed by actual layer ID, never by a display label."""
    by_standard = {str(row.get('standard_name') or ''): row for row in definitions}
    return [dict(by_standard.get(str(layer.customProperty('geoflow/standard_name', '')), {}),
                 layer_id=layer.id(), standard_name=str(layer.customProperty('geoflow/standard_name', '')),
                 label=str(by_standard.get(str(layer.customProperty('geoflow/standard_name', '')), {}).get('label') or '').strip(),
                 row_count=layer.featureCount()) for layer in layers]


DOMAIN_LABELS = {
    "COMMON": "공통",
    "WTL": "상수",
    "SWL": "하수",
    "ROAD": "도로",
}

SYSTEM_FORM_FIELDS = {
    "id",
    "project_id",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
}


def reference_groups(catalog: dict) -> dict[str, list[dict]]:
    return {
        str(row.get("code_group_key") or ""): list(row.get("values") or [])
        for row in catalog.get("groups") or []
        if str(row.get("code_group_key") or "")
    }


def layer_reference_bindings(catalog: dict, standard_name: str) -> list[dict]:
    key = str(standard_name or "").upper()
    return [
        row
        for row in catalog.get("bindings") or []
        if str(row.get("standard_name") or "").upper() == key
    ]


def qgis_value_map(values: list[dict]) -> list[dict[str, str]]:
    return [
        {str(row.get("label") or row.get("code") or ""): str(row.get("code") or "")}
        for row in values
        if str(row.get("code") or "")
    ]


def form_field_label(field: dict) -> str:
    label = str(field.get("label") or "").strip()
    standard_name = str(field.get("standard_name") or "").strip().upper()
    name = str(field.get("name") or "").strip()
    display = label or standard_name or name
    if standard_name and standard_name.casefold() not in display.casefold():
        display += f" [{standard_name}]"
    unit = str(field.get("unit") or "").strip()
    if unit:
        display += f" ({unit})"
    return display


# ============================================================
# 중앙 필드 메타데이터의 QGIS 기본 편집기 변환
# ============================================================
def editor_widget_spec(field: dict, values: list[dict] | None = None) -> tuple[str, dict]:
    """Return a QGIS-native editor setup from the server field contract."""

    name = str(field.get("name") or "")
    if not bool(field.get("visible", True)) or name in SYSTEM_FORM_FIELDS:
        return "Hidden", {}
    value_map = qgis_value_map(values or [])
    if value_map:
        return "ValueMap", {"map": value_map}
    widget_type = str(field.get("widget_type") or "").strip().casefold()
    data_type = str(field.get("data_type") or "").strip().casefold()
    if widget_type == "date" or data_type == "date":
        return "DateTime", {
            "allow_null": True,
            "calendar_popup": True,
            "display_format": "yyyy-MM-dd",
            "field_format": "yyyy-MM-dd",
        }
    if widget_type == "datetime" or data_type.startswith("timestamp"):
        return "DateTime", {
            "allow_null": True,
            "calendar_popup": True,
            "display_format": "yyyy-MM-dd HH:mm:ss",
            "field_format": "yyyy-MM-ddTHH:mm:ss",
        }
    if widget_type in {"boolean", "checkbox"} or data_type == "boolean":
        return "CheckBox", {"CheckedState": "1", "UncheckedState": "0"}
    if widget_type == "json" or data_type in {"json", "jsonb"}:
        return "TextEdit", {"IsMultiline": True}
    return "", {}
