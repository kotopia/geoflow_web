"""Policy precedence and ordered Template/Variant/Slot expansion."""
from unittest import TestCase

from control.services.gis_photo_policy import (
    PhotoPolicyConflict, PhotoPolicyError, _json_object, resolve, validate_extra_schema,
)


def sample():
    return {
        "templates": [
            {"id":"exposed","code":"EXPOSED","name":"노출관로측량","active":True,"sort_order":0},
            {"id":"other","code":"OTHER","name":"기타사진","active":True,"sort_order":1},
        ],
        "variants": [
            {"id":"direct","template_id":"exposed","code":"DIRECT","name":"직접","active":True,"sort_order":0},
            {"id":"indirect","template_id":"exposed","code":"INDIRECT","name":"간접","active":True,"sort_order":1},
            {"id":"default","template_id":"other","code":"DEFAULT","name":"기본","active":True,"sort_order":0},
        ],
        "slots": [
            {"id":"buried","variant_id":"direct","code":"BURIED","active":True,"sort_order":0},
            {"id":"depth","variant_id":"indirect","code":"DEPTH","active":True,"sort_order":0},
            {"id":"misc","variant_id":"default","code":"MISC","active":True,"sort_order":0},
        ],
        "policies": [
            {"id":"water","lv2_id":"water","lv3_id":None,"layer_id":"flow","active":True},
            {"id":"specific","lv2_id":"water","lv3_id":"survey","layer_id":"flow","active":True},
        ],
        "policy_templates": [
            {"id":"w2","policy_id":"water","template_id":"other","active":True,"sort_order":1},
            {"id":"w1","policy_id":"water","template_id":"exposed","active":True,"sort_order":0},
            {"id":"s1","policy_id":"specific","template_id":"exposed","active":True,"sort_order":0},
        ],
    }


class PhotoPolicyResolutionTests(TestCase):
    def test_l3_policy_wins_and_expands_catalogue(self):
        result = resolve(sample(), [("water", "survey")], "flow")
        self.assertEqual(result["policy_id"], "specific")
        self.assertEqual([row["name"] for row in result["templates"]], ["노출관로측량"])
        self.assertEqual([row["name"] for row in result["templates"][0]["variants"]], ["직접", "간접"])
        self.assertEqual(result["templates"][0]["variants"][0]["slots"][0]["id"], "buried")

    def test_l2_fallback_returns_link_order(self):
        result = resolve(sample(), [("water", "other")], "flow")
        self.assertEqual([row["id"] for row in result["templates"]], ["exposed", "other"])

    def test_scopes_are_not_cross_joined(self):
        result = resolve(sample(), [("water", "other"), ("road", "survey")], "flow")
        self.assertEqual(result["policy_id"], "water")

    def test_same_priority_conflict(self):
        data = sample()
        data["policies"].append({**data["policies"][1], "id":"second", "lv3_id":"second"})
        with self.assertRaises(PhotoPolicyConflict):
            resolve(data, [("water", "survey"), ("water", "second")], "flow")

    def test_missing_policy(self):
        data = sample()
        for policy in data["policies"]:
            policy["active"] = False
        self.assertIsNone(resolve(data, [("water", "survey")], "flow"))

    def test_policy_without_active_variant_fails_closed(self):
        data = sample()
        for variant in data["variants"]:
            variant["active"] = False
        with self.assertRaises(PhotoPolicyError):
            resolve(data, [("water", "survey")], "flow")

    def test_extra_schema_and_json_validation(self):
        fields = [{"key":"F1","label":"관로 수","kind":"integer","required":True}]
        self.assertEqual(validate_extra_schema({"fields":fields})["fields"], fields)
        with self.assertRaises(PhotoPolicyError):
            validate_extra_schema({"fields":fields + fields})
        self.assertEqual(_json_object('{"fields":[]}', "사진 항목 추가 입력"), {"fields":[]})
