import unittest

from .photo_selection import resolve_selection


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
