"""QGIS 4 runtime checks for project-scoped display CRS persistence."""
import os
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = PLUGIN_ROOT.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import QApplication, QLabel, QPushButton, QToolButton, QWidget
from qgis.PyQt.uic import loadUi
from qgis.core import (QgsApplication, QgsCoordinateReferenceSystem,
                       QgsCoordinateTransform, QgsFeature, QgsGeometry,
                       QgsPointXY, QgsProject, QgsVectorLayer)

from geoflow_connector.ui.project_crs import ProjectCrsController


APP = QgsApplication.instance() or QgsApplication([], False)
APP.initQgis()


class ProjectCrsTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.settings_path = str(Path(self.temp.name) / "crs.ini")
        self.settings_patch = patch(
            "geoflow_connector.ui.project_crs.QSettings",
            side_effect=lambda: QSettings(
                self.settings_path, QSettings.Format.IniFormat
            ),
        )
        self.settings_patch.start()
        self.canvas = SimpleNamespace(refresh=Mock())
        plugin = SimpleNamespace(iface=SimpleNamespace(mapCanvas=lambda: self.canvas))
        self.name = QLabel()
        self.label = QLabel()
        self.button = QPushButton()
        self.controller = ProjectCrsController(
            plugin, self.name, self.label, self.button
        )
        QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:4326"))

    def tearDown(self):
        self.controller.close()
        self.settings_patch.stop()
        self.temp.cleanup()

    def test_project_scoped_crs_is_restored_and_label_tracks_qgis(self):
        self.controller.activate("project-a", "26003 프로젝트 A")
        self.assertIn("EPSG:4326", self.label.text())
        QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:5186"))
        self.assertIn("EPSG:5186", self.label.text())

        self.controller.activate("project-b", "프로젝트 B")
        self.assertIn("EPSG:5186", self.label.text())
        QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:5187"))
        self.assertIn("EPSG:5187", self.label.text())

        self.controller.activate("project-a", "26003 프로젝트 A")
        self.assertEqual(QgsProject.instance().crs().authid(), "EPSG:5186")
        self.assertEqual(self.name.text(), "26003 프로젝트 A")
        self.assertEqual(self.name.toolTip(), "26003 프로젝트 A")

    def test_main_dock_exposes_compact_project_info_entry(self):
        root = loadUi(str(PLUGIN_ROOT / "ui" / "designer" / "main_dock.ui"))
        info = root.findChild(QToolButton, "GeoFlowRail_info")
        projects = root.findChild(QToolButton, "GeoFlowRail_projects")
        self.assertIsNotNone(info)
        self.assertEqual(
            root.rail_layout.indexOf(info) + 1,
            root.rail_layout.indexOf(projects),
        )
        self.assertIsNone(root.findChild(QWidget, "user_label"))
        self.assertIsNone(root.findChild(QWidget, "projectNameLabel"))
        self.assertIsNone(root.findChild(QWidget, "projectCrsLabel"))
        self.assertIsNone(root.findChild(QWidget, "header"))
        self.assertTrue(root.editModeButton.isCheckable())
        self.assertIsNone(root.findChild(QWidget, "editToolsHost"))
        root.deleteLater()

    def test_project_info_popup_owns_crs_controls(self):
        popup = loadUi(str(
            PLUGIN_ROOT / "ui" / "designer" / "project_info_popup.ui"
        ))
        self.assertIsNotNone(popup.projectNameLabel)
        self.assertIsNotNone(popup.projectCrsLabel)
        self.assertEqual(popup.projectCrsButton.text(), "좌표계 변경")
        popup.deleteLater()

    def test_display_crs_change_never_rewrites_feature_geometry(self):
        layer = QgsVectorLayer("Point?crs=EPSG:4326", "stored", "memory")
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt("POINT (127.405081 36.270687)"))
        self.assertTrue(layer.dataProvider().addFeature(feature))
        before = bytes(next(layer.getFeatures()).geometry().asWkb())
        self.controller.activate("project-a", "A")
        QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:5186"))
        QgsProject.instance().setCrs(QgsCoordinateReferenceSystem("EPSG:5187"))
        after = bytes(next(layer.getFeatures()).geometry().asWkb())
        self.assertEqual(before, after)
        self.assertGreaterEqual(self.canvas.refresh.call_count, 2)

    def test_survey_source_crs_and_project_display_crs_are_independent(self):
        canonical = QgsPointXY(127.4050808, 36.2706871)
        wgs84 = QgsCoordinateReferenceSystem("EPSG:4326")
        for source_authid, display_authid in (
            ("EPSG:5187", "EPSG:5186"),
            ("EPSG:5186", "EPSG:5187"),
        ):
            source = QgsCoordinateReferenceSystem(source_authid)
            raw = QgsCoordinateTransform(
                wgs84, source, QgsProject.instance()
            ).transform(canonical)
            if source_authid == "EPSG:5186":
                self.assertAlmostEqual(raw.x(), 236398.45, delta=0.05)
                self.assertAlmostEqual(raw.y(), 408156.62, delta=0.05)
            QgsProject.instance().setCrs(
                QgsCoordinateReferenceSystem(display_authid)
            )
            restored = QgsCoordinateTransform(
                source, wgs84, QgsProject.instance()
            ).transform(raw)
            self.assertAlmostEqual(restored.x(), canonical.x(), places=6)
            self.assertAlmostEqual(restored.y(), canonical.y(), places=6)


if __name__ == "__main__":
    unittest.main(verbosity=2)
