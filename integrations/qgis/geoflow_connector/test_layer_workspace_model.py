from __future__ import annotations

import unittest

from .layer_workspace_model import (
    filtered_layer_rows,
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


if __name__ == "__main__":
    unittest.main()
