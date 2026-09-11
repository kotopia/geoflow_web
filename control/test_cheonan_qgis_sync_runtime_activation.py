from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.ops.activate_cheonan_qgis_sync_runtime import (
    CONFIRMATION,
    apply,
    planned_lines,
)


class CheonanQgisSyncRuntimeActivationTests(TestCase):
    def test_adds_exact_fail_closed_runtime_values(self):
        updated, state = planned_lines(["OTHER=value\n"])
        self.assertIn("GEOFLOW_GIS_PILOT_ENABLED=1\n", updated)
        self.assertIn("GEOFLOW_GIS_PILOT_DATABASES=cheonan_db\n", updated)
        self.assertFalse(state["already_enabled"])
        self.assertFalse(state["target_already_allowed"])

    def test_refuses_global_activation_with_foreign_dormant_allowlist(self):
        with self.assertRaisesRegex(RuntimeError, "non-cheonan"):
            planned_lines(
                [
                    "GEOFLOW_GIS_PILOT_ENABLED=0\n",
                    "GEOFLOW_GIS_PILOT_DATABASES=other_db\n",
                ]
            )

    def test_preserves_existing_active_allowlist_when_adding_cheonan(self):
        updated, _state = planned_lines(
            [
                "GEOFLOW_GIS_PILOT_ENABLED=1\n",
                "GEOFLOW_GIS_PILOT_DATABASES=existing_db\n",
            ]
        )
        self.assertIn(
            "GEOFLOW_GIS_PILOT_DATABASES=cheonan_db,existing_db\n", updated
        )

    def test_requires_exact_confirmation_and_preserves_mode(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / ".env"
            path.write_text("OTHER=value\n", encoding="utf-8")
            path.chmod(0o640)
            with self.assertRaisesRegex(RuntimeError, "confirmation"):
                apply(path, "wrong")
            apply(path, CONFIRMATION)
            self.assertEqual(path.stat().st_mode & 0o777, 0o640)

    def test_production_workflow_is_exact_and_fail_closed(self):
        workflow = Path(
            ".github/workflows/cheonan-qgis-sync-production-activation.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("environment: production", workflow)
        self.assertIn("ACTIVATE_QGIS_SYNC:cheonan_db:26003", workflow)
        self.assertIn("86f52715-3cca-4124-9cc6-cb7c6a7e9c4e", workflow)
        self.assertIn("connection.set_session(readonly=True", workflow)
        self.assertIn("GIS Changeset support tables are incomplete", workflow)
        self.assertIn("qgis_sync_activation_rollback_completed=yes", workflow)
        self.assertNotIn("print(password", workflow)
