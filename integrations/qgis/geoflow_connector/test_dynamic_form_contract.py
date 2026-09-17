from __future__ import annotations

import unittest

from .forms.dynamic.contract import DefinitionContractError, layer_fields, normalize_definition
from .forms.dynamic.rules import allowed_code_ids, validate


def payload():
    return {
        "ok": True, "version": "gis-final-form-v3", "revision": "rev-1",
        "fields": [
            {"id": "material", "layer_standard_name": "WTL_PIPE_LM", "field_name": "mop_cde",
             "label": "재질", "semantic_data_type": "text", "widget_type": "combo",
             "visible": True, "required": True, "readonly": False, "display_order": 10,
             "storage": {"kind": "column", "key": "mop_cde"},
             "reference_codes": [{"id": "steel", "value": "ST", "label": "강관", "order": 1, "enabled": True}]},
            {"id": "diameter", "layer_standard_name": "WTL_PIPE_LM", "field_name": "pip_dip",
             "label": "구경", "semantic_data_type": "decimal", "widget_type": "combo",
             "visible": True, "required": False, "readonly": False, "display_order": 20,
             "storage": {"kind": "column", "key": "pip_dip"},
             "reference_codes": [{"id": "d100", "value": "100", "label": "100", "order": 1, "enabled": True},
                                 {"id": "d200", "value": "200", "label": "200", "order": 2, "enabled": True}]},
        ],
        "rules": [{"id": "rule", "source_field_id": "material", "source_code_id": "steel",
                   "target_field_id": "diameter", "allowed_code_ids": ["d100"]}],
    }


class DynamicFormContractTests(unittest.TestCase):
    def test_normalizes_and_sorts_the_central_contract(self):
        definition = normalize_definition(payload())
        self.assertEqual([row["id"] for row in layer_fields(definition, "wtl_pipe_lm")],
                         ["material", "diameter"])
        self.assertEqual(definition["revision"], "rev-1")

    def test_rejects_legacy_or_revisionless_payloads(self):
        for update in ({"version": "tenant-form-v1"}, {"revision": ""}):
            value = payload(); value.update(update)
            with self.assertRaises(DefinitionContractError):
                normalize_definition(value)

    def test_rule_filters_and_validation_match_server_semantics(self):
        definition = normalize_definition(payload())
        fields = layer_fields(definition, "WTL_PIPE_LM")
        self.assertEqual(allowed_code_ids(definition, "diameter", {"material": "ST"}), {"d100"})
        self.assertEqual(validate(definition, fields, {"material": "ST", "diameter": "200"}),
                         ["구경 값이 연결 규칙에서 허용되지 않습니다."])
        self.assertEqual(validate(definition, fields, {"material": None, "diameter": None}),
                         ["재질 필드는 필수입니다."])


if __name__ == "__main__":
    unittest.main()
