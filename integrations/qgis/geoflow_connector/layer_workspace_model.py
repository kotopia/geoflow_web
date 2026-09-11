from __future__ import annotations

from collections import OrderedDict


DOMAIN_LABELS = {
    "COMMON": "공통",
    "WTL": "상수",
    "SWL": "하수",
    "ROAD": "도로",
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
