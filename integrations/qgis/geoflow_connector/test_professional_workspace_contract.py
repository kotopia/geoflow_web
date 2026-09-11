from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class ProfessionalWorkspaceContractTests(unittest.TestCase):
    def test_qt_widgets_are_imported_only_through_qgis_pyqt(self):
        source = (ROOT / "layer_workspace.py").read_text(encoding="utf-8")
        self.assertIn("from qgis.PyQt.QtCore import Qt", source)
        self.assertIn("from qgis.PyQt.QtWidgets import (", source)
        self.assertNotIn("from PyQt5", source)
        self.assertNotIn("from PyQt6", source)

    def test_workspace_is_metadata_driven_and_has_no_layer_specific_tabs(self):
        source = (ROOT / "layer_workspace.py").read_text(encoding="utf-8")
        self.assertIn('manifest.get("layers")', source)
        self.assertIn("QTreeWidget", source)
        self.assertNotIn("QTabWidget", source)
        for legacy_module in ("WtlPipeLmQuickEdit", "WtlValvPsQuickEdit", "Yeoju_Swater"):
            self.assertNotIn(legacy_module, source)

    def test_workspace_opens_one_native_form_for_add_and_edit(self):
        source = (ROOT / "layer_workspace.py").read_text(encoding="utf-8")
        self.assertIn('QPushButton("선택 속성 입력·수정")', source)
        self.assertIn("openFeatureForm", source)
        self.assertIn("config.setSuppress(suppress_off)", source)
        self.assertIn("editor_widget_spec(field, values)", source)
        self.assertIn("field.get(\"required\")", source)

    def test_production_delta_polling_does_not_require_websocket_runtime(self):
        source = (ROOT / "realtime_delta.py").read_text(encoding="utf-8")
        transport_method = source.split("def _realtime_transport_available", 1)[1].split(
            "def _realtime_websocket_available", 1
        )[0]
        self.assertNotIn('transport.get("realtime_supported")', transport_method)
        websocket_method = source.split("def _realtime_websocket_available", 1)[1].split(
            "def _cookie_header", 1
        )[0]
        self.assertIn('transport.get("realtime_supported")', websocket_method)


if __name__ == "__main__":
    unittest.main()
