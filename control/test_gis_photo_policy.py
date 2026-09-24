"""Policy precedence and per-feature mode are independent of the database UI."""
from unittest import TestCase

from control.services.gis_photo_policy import (
    PhotoPolicyConflict, PhotoPolicyError, capture_mode, resolve, validate_extra_schema,
)


def sample():
    return {
        "templates":[
            {"id":"direct","active":True,"capture_mode":"DIRECT","name":"직접"},
            {"id":"indirect","active":True,"capture_mode":"INDIRECT","name":"간접"},
        ],
        "slots":[
            {"id":"buried","template_id":"direct","active":True,"min_count":1},
            {"id":"depth","template_id":"indirect","active":True,"min_count":1},
        ],
        "policies":[
            {"id":"water","lv2_id":"water","lv3_id":None,"layer_id":"valve",
             "active":True,"default_capture_mode":"DIRECT","direct_template_id":"direct",
             "indirect_template_id":"indirect","allow_extra_photo":True},
            {"id":"exposed","lv2_id":"water","lv3_id":"exposed","layer_id":"valve",
             "active":True,"default_capture_mode":"DIRECT","direct_template_id":"direct",
             "indirect_template_id":"indirect","allow_extra_photo":False},
        ],
    }


class PhotoPolicyResolutionTests(TestCase):
    def test_l3_policy_wins_for_paired_scope(self):
        result = resolve(sample(),[("water","exposed")],"valve")
        self.assertEqual(result["policy_id"],"exposed")
        self.assertEqual(result["capture_mode"],"DIRECT")
        self.assertEqual(result["template"]["slots"][0]["id"],"buried")

    def test_l2_fallback_and_indirect_feature(self):
        result = resolve(sample(),[("water","survey")],"valve",
                         {"photo":{"capture_mode":"INDIRECT"}})
        self.assertEqual(result["policy_id"],"water")
        self.assertEqual(result["template"]["slots"][0]["id"],"depth")

    def test_scopes_are_not_cross_joined(self):
        result = resolve(sample(),[("water","survey"),("road","exposed")],"valve")
        self.assertEqual(result["policy_id"],"water")

    def test_multiple_l3_policies_same_layer_conflict(self):
        data=sample()
        data["policies"].append({**data["policies"][1],"id":"exploration","lv3_id":"exploration"})
        with self.assertRaises(PhotoPolicyConflict):
            resolve(data,[("water","exposed"),("water","exploration")],"valve")

    def test_inactive_and_missing_policy(self):
        data=sample()
        for policy in data["policies"]: policy["active"]=False
        self.assertIsNone(resolve(data,[("water","exposed")],"valve"))

    def test_invalid_mode_is_not_silently_direct(self):
        with self.assertRaises(PhotoPolicyError):
            capture_mode({"photo":{"capture_mode":"OTHER"}})

    def test_extra_schema_rejects_unknown_kind_and_duplicate_key(self):
        fields=[{"key":"F1","label":"관로 수","kind":"integer","required":True}]
        self.assertEqual(validate_extra_schema({"fields":fields})["fields"],fields)
        with self.assertRaises(PhotoPolicyError):
            validate_extra_schema({"fields":fields+fields})
