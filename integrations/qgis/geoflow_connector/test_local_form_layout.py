# 제목: 로컬 사용자 속성폼 배치 테스트
# 기능: 중앙 필드와 분리된 레이어별 Tab·Group·Row·Field 배치 및 미배치 처리를 검증
from __future__ import annotations

import unittest

from .forms.dynamic.layout_model import (
    default_layout, normalize_layout, placed_field_ids, render_layout, unplaced_fields,
)


def fields():
    return [
        {"id": "worker", "name": "worker", "label": "작업자", "visible": True,
         "widget_type": "text", "layout": {"tab": "기본 정보", "section": "기본 속성"}},
        {"id": "work_date", "name": "work_date", "label": "작업일", "visible": True,
         "widget_type": "date", "layout": {"tab": "기본 정보", "section": "기본 속성"}},
        {"id": "code", "name": "saa_cde", "label": "시설물 코드", "visible": True,
         "widget_type": "text", "layout": {}},
        {"id": "secret", "name": "secret", "label": "숨김", "visible": False,
         "widget_type": "hidden", "layout": {}},
    ]


class LocalFormLayoutTests(unittest.TestCase):
    def test_default_layout_preserves_existing_tab_group_and_field_order(self):
        value = default_layout("wtl_valv_ps", fields())
        self.assertEqual(value["layer"], "WTL_VALV_PS")
        self.assertEqual(value["tabs"][0]["title"], "기본 정보")
        self.assertEqual(value["tabs"][0]["groups"][0], {
            "title": "기본 속성", "rows": [["worker"], ["work_date"]],
        })
        self.assertEqual(value["tabs"][0]["groups"][1], {
            "title": "속성", "rows": [["code"]],
        })
        self.assertNotIn("secret", placed_field_ids(value))

    def test_multiple_fields_share_a_row_and_unknown_or_duplicate_ids_are_removed(self):
        value = normalize_layout({
            "layer": "WTL_VALV_PS",
            "tabs": [{"title": "현장", "groups": [{"title": "작업", "rows": [
                ["worker", "work_date", "missing"], ["worker"],
            ]}]}],
        }, "WTL_VALV_PS", fields())
        self.assertEqual(value["tabs"][0]["groups"][0]["rows"], [["worker", "work_date"]])

    def test_new_central_field_is_reported_and_rendered_as_unplaced(self):
        value = {"layer": "WTL_VALV_PS", "tabs": [{
            "title": "기본 정보", "groups": [{"title": "기본", "rows": [["worker"]]}],
        }]}
        self.assertEqual(
            [field["id"] for field in unplaced_fields(value, fields())],
            ["work_date", "code"],
        )
        rendered = render_layout(value, "WTL_VALV_PS", fields())
        self.assertEqual(rendered["tabs"][-1]["groups"][-1], {
            "title": "미배치 필드", "rows": [["work_date"], ["code"]],
        })

    def test_other_layer_layout_is_rejected_and_local_data_has_no_field_definition_copy(self):
        value = normalize_layout({
            "layer": "WTL_PIPE_LM", "tabs": [],
        }, "WTL_VALV_PS", fields())
        self.assertIsNone(value)
        keys = set(default_layout("WTL_VALV_PS", fields()))
        self.assertEqual(keys, {"version", "layer", "tabs"})

    def test_empty_group_and_row_are_preserved_for_later_field_placement(self):
        value = normalize_layout({
            "layer": "WTL_VALV_PS",
            "tabs": [{"title": "기본 정보", "groups": [
                {"title": "새 그룹", "rows": [[]]},
            ]}],
        }, "WTL_VALV_PS", fields())
        self.assertEqual(value["tabs"][0]["groups"][0], {
            "title": "새 그룹", "rows": [[]],
        })


if __name__ == "__main__":
    unittest.main()
