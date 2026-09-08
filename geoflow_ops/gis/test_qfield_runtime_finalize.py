from __future__ import annotations

from django.test import SimpleTestCase

from .qfield_runtime_finalize import _finalize_qml


class QFieldRuntimeFinalizeTests(SimpleTestCase):
    def source(self):
        from pathlib import Path
        from .qfield_package import _render_qfield_plugin
        from .qfield_persistent import _inject_qml_persistent_session
        root = Path(__file__).resolve().parents[2]
        return _inject_qml_persistent_session(_render_qfield_plugin(root / 'integrations/qfield/geoflow-field.qml'))

    def test_foreground_claim_and_retry_require_active_auth(self):
        source = self.source()
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
        source = self.source()
        once = _finalize_qml(source)
        twice = _finalize_qml(once)
        self.assertEqual(once, twice)
        self.assertEqual(twice.count("target: Qt.application"), 1)
