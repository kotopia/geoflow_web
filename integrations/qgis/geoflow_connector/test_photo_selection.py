import unittest

from .photo_selection import next_photo_slot, photo_classification_options, resolve_selection


POLICY = {"templates": [
    {"id":"exposed", "variants":[{"id":"direct"}, {"id":"indirect"}]},
    {"id":"other", "variants":[{"id":"default"}]},
]}


class PhotoSelectionTests(unittest.TestCase):
    def test_first_entry_uses_first_template_and_variant(self):
        self.assertEqual(resolve_selection(POLICY), ("exposed", "direct"))

    def test_valid_recent_selection_is_restored(self):
        self.assertEqual(resolve_selection(POLICY, "exposed", "indirect"), ("exposed", "indirect"))
        self.assertEqual(resolve_selection(POLICY, "other", "default"), ("other", "default"))

    def test_stale_values_fall_back(self):
        self.assertEqual(resolve_selection(POLICY, "deleted", "deleted"), ("exposed", "direct"))
        self.assertEqual(resolve_selection(POLICY, "exposed", "deleted"), ("exposed", "direct"))

    def test_template_specific_variant_is_used(self):
        self.assertEqual(resolve_selection(POLICY, "exposed", "",
                         {"exposed":"indirect"}), ("exposed", "indirect"))

    def test_next_slot_satisfies_minimums_in_definition_order(self):
        variant = {"slots": [
            {"id":"buried", "min_count":1, "max_count":1},
            {"id":"paved", "min_count":1, "max_count":2},
        ]}
        self.assertEqual(next_photo_slot(variant, [])["id"], "buried")
        self.assertEqual(next_photo_slot(variant, [{"slot_id":"buried"}])["id"], "paved")
        photos = [{"slot_id":"buried"}, {"slot_id":"paved"}]
        self.assertEqual(next_photo_slot(variant, photos, "paved")["id"], "paved")

    def test_pending_classification_options_preserve_catalogue_order(self):
        policy = {"templates":[{"id":"exposed", "name":"노출관로", "variants":[
            {"id":"direct", "name":"직접", "slots":[{"id":"buried", "name":"매설"}]},
            {"id":"indirect", "name":"간접", "slots":[{"id":"offset", "name":"이격"}]},
        ]}]}
        options = photo_classification_options(policy)
        self.assertEqual([row["slot_id"] for row in options], ["buried", "offset", ""])
        self.assertEqual(options[-1]["label"], "추가 사진")
