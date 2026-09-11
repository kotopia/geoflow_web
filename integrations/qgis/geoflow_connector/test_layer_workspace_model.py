from __future__ import annotations

import unittest

from .layer_workspace_model import (
    editor_widget_spec,
    filtered_layer_rows,
    form_field_label,
    grouped_layer_rows,
    layer_reference_bindings,
    qgis_value_map,
    reference_groups,
    setting_enabled,
)


class LayerWorkspaceModelTests(unittest.TestCase):
    def setUp(self):
        self.rows = [
            {
                "domain": "WTL",
                "label": "상수관로",
                "standard_name": "WTL_PIPE_LM",
                "physical_name": "wtl_pipe_lm",
            },
            {
                "domain": "SWL",
                "label": "하수맨홀",
                "standard_name": "SWL_MANH_PS",
                "physical_name": "swl_manh_ps",
            },
            {
                "domain": "WTL",
                "label": "제수밸브",
                "standard_name": "WTL_VALV_PS",
                "physical_name": "wtl_valv_ps",
            },
        ]

    def test_search_matches_label_standard_and_physical_names(self):
        self.assertEqual(
            [row["standard_name"] for row in filtered_layer_rows(self.rows, "관로")],
            ["WTL_PIPE_LM"],
        )
        self.assertEqual(
            [
                row["standard_name"]
                for row in filtered_layer_rows(self.rows, "swl_manh")
            ],
            ["SWL_MANH_PS"],
        )

    def test_rows_are_grouped_without_per_layer_tabs(self):
        grouped = grouped_layer_rows(self.rows)
        self.assertEqual(list(grouped), ["SWL", "WTL"])
        self.assertEqual(len(grouped["WTL"]), 2)

    def test_reference_catalog_drives_qgis_value_map(self):
        catalog = {
            "bindings": [
                {
                    "standard_name": "WTL_PIPE_LM",
                    "field_name": "mop_cde",
                    "code_group_key": "WTL.PIPE.MATERIAL",
                }
            ],
            "groups": [
                {
                    "code_group_key": "WTL.PIPE.MATERIAL",
                    "values": [
                        {"code": "MOP001", "label": "DCIP"},
                        {"code": "MOP004", "label": "PE"},
                    ],
                }
            ],
        }
        bindings = layer_reference_bindings(catalog, "wtl_pipe_lm")
        self.assertEqual(bindings[0]["field_name"], "mop_cde")
        groups = reference_groups(catalog)
        self.assertEqual(
            qgis_value_map(groups["WTL.PIPE.MATERIAL"]),
            [{"DCIP": "MOP001"}, {"PE": "MOP004"}],
        )

    def test_qgis_string_custom_properties_are_parsed_safely(self):
        self.assertTrue(setting_enabled(True))
        self.assertTrue(setting_enabled("1"))
        self.assertFalse(setting_enabled("false"))
        self.assertFalse(setting_enabled("0"))

    def test_geoflow_field_contract_selects_native_form_widgets(self):
        self.assertEqual(
            form_field_label(
                {
                    "name": "saa_cde",
                    "standard_name": "SAA_CDE",
                    "label": "상수관 용도",
                }
            ),
            "상수관 용도 [SAA_CDE]",
        )
        self.assertEqual(
            form_field_label(
                {
                    "name": "pip_dep",
                    "standard_name": "PIP_DEP",
                    "label": "심도",
                    "unit": "m",
                }
            ),
            "심도 [PIP_DEP] (m)",
        )
        self.assertEqual(
            editor_widget_spec(
                {
                    "name": "saa_cde",
                    "standard_name": "SAA_CDE",
                    "visible": True,
                    "widget_type": "text",
                },
                [
                    {"code": "배수관", "label": "배수관"},
                    {"code": "송수관", "label": "송수관"},
                ],
            ),
            ("ValueMap", {"map": [{"배수관": "배수관"}, {"송수관": "송수관"}]}),
        )
        self.assertEqual(
            editor_widget_spec(
                {"name": "ist_ymd", "visible": True, "widget_type": "date"}
            )[0],
            "DateTime",
        )
        self.assertEqual(
            editor_widget_spec(
                {"name": "ext_data", "visible": True, "data_type": "jsonb"}
            ),
            ("TextEdit", {"IsMultiline": True}),
        )
        self.assertEqual(
            editor_widget_spec({"name": "project_id", "visible": True}),
            ("Hidden", {}),
        )

    def test_initial_water_layers_share_the_generic_form_engine(self):
        cases = {
            "WTL_PIPE_LM": {
                "name": "saa_cde",
                "standard_name": "SAA_CDE",
                "label": "상수관 용도",
            },
            "WTL_PIPE_PS": {
                "name": "pip_dep",
                "standard_name": "PIP_DEP",
                "label": "심도",
                "unit": "m",
            },
            "WTL_VALV_PS": {
                "name": "cst_cde",
                "standard_name": "CST_CDE",
                "label": "이상 상태",
            },
            "WTL_FIRE_PS": {
                "name": "fire_dip",
                "standard_name": "FIRE_DIP",
                "label": "소화전 구경",
                "unit": "mm",
            },
        }
        self.assertEqual(set(cases), {
            "WTL_PIPE_LM", "WTL_PIPE_PS", "WTL_VALV_PS", "WTL_FIRE_PS"
        })
        for field in cases.values():
            self.assertTrue(form_field_label({**field, "visible": True}))
            self.assertEqual(
                editor_widget_spec({**field, "visible": True}),
                ("", {}),
            )
        valve_widget = editor_widget_spec(
            {**cases["WTL_VALV_PS"], "visible": True},
            [{"code": "CST001", "label": "정상"}],
        )
        self.assertEqual(valve_widget, ("ValueMap", {"map": [{"정상": "CST001"}]}))


if __name__ == "__main__":
    unittest.main()
