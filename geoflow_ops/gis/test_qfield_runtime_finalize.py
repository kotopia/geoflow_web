from __future__ import annotations

from django.test import SimpleTestCase

from .qfield_runtime_finalize import _finalize_qml


class QFieldRuntimeFinalizeTests(SimpleTestCase):
    def test_foreground_claim_and_retry_require_active_auth(self):
        source = '''Item {
    Timer {
        id: syncTimer
        interval: 3000
        repeat: true
        running: geoflowField.unsyncedCount > 0
        onTriggered: geoflowField.syncNow(false, false)
    }
    function log(message) {}
}
'''
        text = _finalize_qml(source)
        self.assertIn("target: Qt.application", text)
        self.assertIn("Qt.ApplicationActive", text)
        self.assertIn("claimPendingSession(false", text)
        self.assertIn("if (!geoflowField.sessionAuthorized())", text)
        self.assertNotIn("if (geoflowField.serverAuthRequired)", text)
        self.assertIn(
            "running: geoflowField.unsyncedCount > 0 && geoflowField.sessionAuthorized()",
            text,
        )
        self.assertNotIn(
            "running: geoflowField.unsyncedCount > 0\n",
            text,
        )

    def test_finalize_is_idempotent(self):
        source = '''Item {
    Timer {
        id: syncTimer
        running: geoflowField.unsyncedCount > 0
    }
    function log(message) {}
}
'''
        once = _finalize_qml(source)
        twice = _finalize_qml(once)
        self.assertEqual(once, twice)
        self.assertEqual(twice.count("target: Qt.application"), 1)
