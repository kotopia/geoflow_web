import datetime as dt
import unittest

from .forms.dynamic.system_defaults import new_feature_defaults


class SystemDefaultTests(unittest.TestCase):
    FIELDS = [
        {"id": "date-id", "label": "작업일", "semantic_data_type": "date",
         "storage": {"kind": "column", "key": "survey_date"}},
        {"id": "worker-id", "label": "작업자", "semantic_data_type": "relation",
         "storage": {"kind": "column", "key": "worker_id"}},
    ]

    def test_new_feature_receives_today_and_linked_worker(self):
        defaults = new_feature_defaults(
            self.FIELDS,
            {"date-id": "2000-01-01", "worker-id": None},
            {"worker_link_status": "linked", "worker_id": "employee-uuid"},
            today=dt.date(2026, 9, 29),
        )
        self.assertEqual(defaults, {
            "date-id": "2026-09-29", "worker-id": "employee-uuid"
        })

    def test_existing_values_and_unlinked_worker_are_preserved(self):
        defaults = new_feature_defaults(
            self.FIELDS,
            {"date-id": "2024-02-03", "worker-id": "historical-worker"},
            {"worker_link_status": "unlinked", "worker_id": "other"},
            today=dt.date(2026, 9, 29),
        )
        self.assertEqual(defaults, {})

    def test_unrelated_date_field_is_not_defaulted(self):
        fields = [{"id": "expiry", "label": "만료일", "semantic_data_type": "date",
                   "storage": {"kind": "column", "key": "expires_on"}}]
        self.assertEqual(new_feature_defaults(fields, {"expiry": None}, {}, today=dt.date(2026, 9, 29)), {})


if __name__ == "__main__":
    unittest.main()
