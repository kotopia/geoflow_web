# GeoFlow QGIS 플러그인 - 로컬 속성폼 배치 모델
# 중앙 필드 정의와 분리된 Tab → Group → Row → Field 화면 배치만 정규화한다.
from __future__ import annotations

from collections import OrderedDict
from copy import deepcopy


LAYOUT_VERSION = 1


def row_field_id(value):
    if isinstance(value, dict):
        return str(value.get("field") or "")
    return str(value or "")


def row_field_weight(value):
    if not isinstance(value, dict) or value.get("weight") in (None, "", 0, "0"):
        return 1
    try:
        return max(1, int(value["weight"]))
    except (TypeError, ValueError):
        return 1


def _visible_fields(fields):
    """화면 배치 대상만 추린다. 중앙 visible/widget_type 판단은 변경하지 않는다."""
    return [
        field for field in fields
        if field.get("visible", True) and field.get("widget_type") != "hidden"
    ]


# ============================================================
# 중앙 정의를 이용한 기본 화면 배치
# ============================================================
def default_layout(layer, fields):
    """기존 tab/section 및 필드 정렬을 보존한 기본 로컬 배치를 만든다."""
    grouped = OrderedDict()
    for field in _visible_fields(fields):
        metadata = field.get("layout") if isinstance(field.get("layout"), dict) else {}
        tab = str(metadata.get("tab") or "기본 정보").strip()
        group = str(metadata.get("section") or "속성").strip()
        grouped.setdefault(tab, OrderedDict()).setdefault(group, []).append(
            [str(field["id"])]
        )
    return {
        "version": LAYOUT_VERSION,
        "layer": str(layer or "").upper(),
        "tabs": [
            {
                "title": tab_title,
                "groups": [
                    {"title": group_title, "rows": rows}
                    for group_title, rows in groups.items()
                ],
            }
            for tab_title, groups in grouped.items()
        ],
    }


# ============================================================
# 저장된 사용자 배치 검증
# ============================================================
def normalize_layout(layout, layer, fields):
    """현재 레이어의 유효한 필드 ID만 남기고 중복·손상된 배치를 제거한다."""
    if not isinstance(layout, dict) or not isinstance(layout.get("tabs"), list):
        return None
    expected_layer = str(layer or "").upper()
    stored_layer = str(layout.get("layer") or "").upper()
    if stored_layer and stored_layer != expected_layer:
        return None

    available = {str(field["id"]) for field in _visible_fields(fields)}
    seen = set()
    tabs = []
    for tab_index, raw_tab in enumerate(layout["tabs"]):
        if not isinstance(raw_tab, dict) or not isinstance(raw_tab.get("groups"), list):
            continue
        groups = []
        for group_index, raw_group in enumerate(raw_tab["groups"]):
            if not isinstance(raw_group, dict) or not isinstance(raw_group.get("rows"), list):
                continue
            rows = []
            for raw_row in raw_group["rows"]:
                if not isinstance(raw_row, list):
                    continue
                row = []
                for raw_value in raw_row:
                    field_id = row_field_id(raw_value)
                    if field_id in available and field_id not in seen:
                        seen.add(field_id)
                        if isinstance(raw_value, dict) and raw_value.get("weight") not in (None, "", 0, "0"):
                            row.append({"field": field_id, "weight": row_field_weight(raw_value)})
                        else:
                            row.append(field_id)
                # 사용자가 만든 빈 행은 유지하되, 중복/삭제 필드만 있던 행은 제거한다.
                if row or not raw_row:
                    rows.append(row)
            groups.append({
                "title": str(raw_group.get("title") or f"그룹 {group_index + 1}").strip(),
                "rows": rows,
            })
        tabs.append({
            "title": str(raw_tab.get("title") or f"탭 {tab_index + 1}").strip(),
            "groups": groups,
        })
    return {
        "version": LAYOUT_VERSION,
        "layer": expected_layer,
        "tabs": tabs,
    }


def placed_field_ids(layout):
    """배치된 필드 ID를 화면 순서대로 반환한다."""
    return [
        field_id
        for tab in (layout or {}).get("tabs", [])
        for group in tab.get("groups", [])
        for row in group.get("rows", [])
        for value in row
        for field_id in [row_field_id(value)]
    ]


def unplaced_fields(layout, fields):
    """중앙에 새로 생겼지만 로컬 배치에는 아직 없는 필드를 찾는다."""
    placed = set(placed_field_ids(layout))
    return [field for field in _visible_fields(fields) if str(field["id"]) not in placed]


def render_layout(layout, layer, fields):
    """미배치 필드도 숨기지 않고 마지막 안내 그룹에 포함한 렌더 배치를 만든다."""
    normalized = normalize_layout(layout, layer, fields) or default_layout(layer, fields)
    completed = deepcopy(normalized)
    missing = unplaced_fields(completed, fields)
    if missing:
        if not completed["tabs"]:
            completed["tabs"].append({"title": "기본 정보", "groups": []})
        completed["tabs"][-1]["groups"].append({
            "title": "미배치 필드",
            "rows": [[str(field["id"])] for field in missing],
        })
    return completed
