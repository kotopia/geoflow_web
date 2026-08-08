from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class EventApiSecurityStaticTests(unittest.TestCase):
    def test_event_writes_are_csrf_protected_and_tenant_guarded(self):
        source = (ROOT / "views_events.py").read_text(encoding="utf-8")
        self.assertNotIn("csrf_exempt", source)
        self.assertIn("require_tenant_context(request)", source)
        self.assertIn("get_event_for_access(request, alias, event_id, write=True)", source)
        self.assertIn('ALLOWED_STATUSES = {"draft", "open", "done", "void"}', source)

    def test_event_errors_do_not_echo_exception_strings(self):
        source = (ROOT / "views_events.py").read_text(encoding="utf-8")
        self.assertNotIn('f"Failed to create event: {', source)
        self.assertNotIn('f"Failed to update event: {', source)
        self.assertNotIn('f"Failed to list events: {', source)
