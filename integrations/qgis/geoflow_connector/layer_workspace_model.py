from __future__ import annotations

from collections import OrderedDict


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


def layer_search_text(row: dict) -> str:
    return " ".join(
        str(row.get(key) or "")
        for key in ("label", "standard_name", "physical_name", "domain")
    ).casefold()


def filtered_layer_rows(rows: list[dict], query: str = "") -> list[dict]:
    needle = str(query or "").strip().casefold()
    selected = [row for row in rows if not needle or needle in layer_search_text(row)]
    return sorted(
        selected,
        key=lambda row: (
            str(row.get("domain") or "OTHER"),
            str(row.get("label") or row.get("standard_name") or "").casefold(),
        ),
    )


def grouped_layer_rows(rows: list[dict], query: str = "") -> OrderedDict[str, list[dict]]:
    grouped: OrderedDict[str, list[dict]] = OrderedDict()
    for row in filtered_layer_rows(rows, query):
        domain = str(row.get("domain") or "OTHER").upper()
        grouped.setdefault(domain, []).append(row)
    return grouped


def domain_label(domain: str) -> str:
    key = str(domain or "OTHER").upper()
    return DOMAIN_LABELS.get(key, key if key != "OTHER" else "기타")


def setting_enabled(value) -> bool:
    if isinstance(value, str):
        return value.strip().casefold() not in {"", "0", "false", "no", "off"}
    return bool(value)


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
