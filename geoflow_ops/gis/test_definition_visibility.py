import unittest

from geoflow_ops.gis.central_definitions import reference_payload, resolve


LAYER = {
    "id": "11111111-1111-1111-1111-111111111111",
    "standard_name": "WTL_TEST_PS",
    "physical_name": "wtl_test_ps",
    "label": "테스트",
}


def base_data(fields):
    return {
        "groups": [],
        "layers": [LAYER],
        "fields": fields,
        "group_fields": [],
        "codes": [],
        "rules": [],
    }


def field(**overrides):
    value = {
        "id": "22222222-2222-2222-2222-222222222222",
        "source_layer_id": LAYER["id"],
        "physical_name": "test_value",
        "standard_name": "TEST_VALUE",
        "label": "테스트 값",
        "storage_data_type": "text",
        "kind": "text",
        "widget_type": "text",
        "visible": True,
        "form_visible": None,
        "table_visible": None,
        "required": False,
        "readonly": False,
        "default_value": None,
        "sort_order": 1,
        "unit": "",
        "description": "",
        "layout": {},
        "active": True,
    }
    value.update(overrides)
    return value


class DefinitionVisibilityTests(unittest.TestCase):
    def test_inactive_field_is_not_resolved(self):
        payload = resolve(
            base_data([field(active=False)]),
            {"group_id": None, "additions": {}, "private_items": {}, "overrides": {}},
            [LAYER],
        )
        self.assertEqual(payload["fields"], [])

    def test_new_visibility_flags_are_independent_and_visible_is_preserved(self):
        payload = resolve(
            base_data([field(visible=True, form_visible=False, table_visible=True)]),
            {"group_id": None, "additions": {}, "private_items": {}, "overrides": {}},
            [LAYER],
        )
        result = payload["fields"][0]
        self.assertFalse(result["visible"])
        self.assertFalse(result["form_visible"])
        self.assertTrue(result["table_visible"])

    def test_inactive_field_is_excluded_from_reference_payload(self):
        inactive = field(active=False)
        data = base_data([inactive])
        data["codes"] = [{
            "id": "33333333-3333-3333-3333-333333333333",
            "field_id": inactive["id"],
            "code": "A",
            "label": "A",
            "sort_order": 1,
            "enabled": True,
        }]
        payload = reference_payload(data, [LAYER["id"]])
        self.assertEqual(payload["bindings"], [])
        self.assertEqual(payload["groups"], [])

    def test_legacy_visible_remains_fallback(self):
        payload = resolve(
            base_data([field(visible=False, form_visible=None, table_visible=None)]),
            {"group_id": None, "additions": {}, "private_items": {}, "overrides": {}},
            [LAYER],
        )
        result = payload["fields"][0]
        self.assertFalse(result["visible"])
        self.assertFalse(result["form_visible"])
        self.assertFalse(result["table_visible"])


if __name__ == "__main__":
    unittest.main()
