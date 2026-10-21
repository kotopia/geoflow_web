"""Local QGIS runtime with mock HTTP. No operational API or facility DB writes."""
import json
import tempfile
import unittest
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from qgis.PyQt.QtCore import QSettings, QTimer
from qgis.PyQt.QtWidgets import QMainWindow, QDockWidget, QStackedWidget, QPushButton, QMenu, QWidget
from qgis.PyQt.uic import loadUi
from qgis.core import (QgsApplication, QgsVectorLayer, QgsFeature, QgsGeometry, QgsCoordinateReferenceSystem,
                       QgsDefaultValue, QgsPointXY, QgsVectorLayerUtils, Qgis)

from geoflow_connector.survey.controller import SurveyController
from geoflow_connector.ui.survey_panel import SurveyPanel, ImportDialog
from geoflow_connector.app.survey_integration import SurveyIntegrationMixin
from geoflow_connector.app.integration import IntegrationEvents


APP = QgsApplication.instance() or QgsApplication([], False)
APP.initQgis()
PROJECT = "10000000-0000-4000-8000-000000000001"
SURVEY = "50000000-0000-4000-8000-000000000001"
TARGET = "60000000-0000-4000-8000-000000000001"
MAPPING = "40000000-0000-4000-8000-000000000003"


def memory_layer(kind="Point", wkt="POINT (1 2)"):
    layer = QgsVectorLayer(kind + "?crs=EPSG:4326&field=id:string", "test", "memory")
    layer.setCustomProperty("geoflow/standard_name", "TEST_LAYER")
    feature = QgsFeature(layer.fields()); feature.setAttribute("id", TARGET)
    feature.setGeometry(QgsGeometry.fromWkt(wkt))
    assert layer.dataProvider().addFeature(feature)
    fid = next(layer.getFeatures()).id(); layer.selectByIds([fid])
    return layer, fid


def engine(layer):
    client = Mock(base_url="https://example.invalid", session_user={"user_id": PROJECT})
    client.get_json.return_value = {"server_envelope": [{"id": SURVEY}]}
    client.post_json.return_value = {"ok": True}
    context = dict(project_id=PROJECT, client_id=PROJECT, changeset_supported=True,
                   delta_url="/existing-delta", package_path="unused")
    plugin = SimpleNamespace(active_client=client, active_context=context,
        _sync_in_progress=False, _suppress_auto_sync=False, work=None,
        integration_state=lambda: dict(ready=True, can_write=True, project_id=PROJECT, epoch=1),
        _managed_layers=lambda: [layer], _sync_active_project=Mock(return_value={"ok": True}),
        iface=SimpleNamespace(activeLayer=lambda: layer, mapCanvas=lambda: Mock()), render_state=Mock(), _leave_survey=Mock())
    return plugin


@unittest.skip("legacy generated UI assertions replaced by qgis_survey_popup_runtime.py")
class ImportDialogRuntimeTests(unittest.TestCase):
    def test_csv_crs_mapping_preview_and_xls_rejection(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'survey.csv'
            path.write_text('id,x,y,z\n' + '\n'.join(f'P{i},200000,500000,12' for i in range(12)), encoding='utf-8-sig')
            dialog = ImportDialog(); dialog.load_file(str(path))
            self.assertEqual(dialog.preview.topLevelItemCount(), 10)
            self.assertFalse(dialog.crs.crs().isValid())
            for name, column in (('source_row_id', 'id'), ('X / longitude', 'x'), ('Y / latitude', 'y')):
                box = dialog.columns[name]; box.setCurrentIndex(box.findData(column))
            dialog.build()
            self.assertIsNone(dialog.payload)
            self.assertIn('좌표계', dialog.error.text())
            dialog.crs.setCrs(QgsCoordinateReferenceSystem('EPSG:5186'))
            dialog.build()
            self.assertEqual(len(dialog.payload['points']), 12)
            self.assertEqual(dialog.payload['source_crs'], 'EPSG:5186')
            dialog.load_file(str(Path(folder) / 'unsupported.xls'))
            self.assertIn('XLS 형식은 지원하지 않습니다', dialog.error.text())
            self.assertIsNone(dialog.payload)
            dialog.deleteLater()

    def test_xlsx_sheet_choice_geographic_and_invalid_number(self):
        from openpyxl import Workbook
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / 'survey.xlsx'
            book = Workbook(); book.active.title = 'first'
            book.active.append(['id', 'lon', 'lat']); book.active.append(['P1', 127, 36])
            sheet = book.create_sheet('second'); sheet.append(['id', 'lon', 'lat']); sheet.append(['P2', 'bad', 36])
            book.save(path); book.close()
            dialog = ImportDialog(); dialog.load_file(str(path))
            self.assertEqual(dialog.sheet.count(), 2)
            dialog.coordinates.setCurrentIndex(1)
            for name, column in (('source_row_id', 'id'), ('X / longitude', 'lon'), ('Y / latitude', 'lat')):
                box = dialog.columns[name]; box.setCurrentIndex(box.findData(column))
            dialog.build()
            self.assertEqual(dialog.payload['points'][0]['longitude'], 127)
            dialog.sheet.setCurrentIndex(1)
            self.assertIsNone(dialog.payload)
            for name, column in (('source_row_id', 'id'), ('X / longitude', 'lon'), ('Y / latitude', 'lat')):
                box = dialog.columns[name]; box.setCurrentIndex(box.findData(column))
            dialog.build()
            self.assertIn('2행', dialog.error.text()); self.assertIn('bad', dialog.error.text())
            self.assertIsNone(dialog.payload)
            dialog.deleteLater()


class EditRuntimeTests(unittest.TestCase):



    def test_split_uuid_and_vertex_probe(self):
        layer, fid = memory_layer("LineString", "LINESTRING (0 0, 10 0, 20 0, 30 0)")
        layer.setDefaultValueDefinition(layer.fields().indexOf("id"),
            QgsDefaultValue("replace(replace(uuid(), '{', ''), '}', '')"))
        layer.startEditing()
        events = []
        layer.featureAdded.connect(lambda new_fid: events.append({
            "fid": new_fid, "uuid_at_featureAdded": str(layer.getFeature(new_fid)["id"])}))
        result = layer.splitFeatures([QgsPointXY(15, -5), QgsPointXY(15, 5)], False)
        rows = [{"fid": f.id(), "uuid": str(f["id"]), "vertices": [[p.x(), p.y()] for p in f.geometry().vertices()]}
                for f in layer.getFeatures()]
        self.assertEqual(int(result), 0); self.assertEqual(len(rows), 2)
        self.assertEqual(next(row for row in rows if row["fid"] == fid)["uuid"], TARGET)
        self.assertEqual(len(events), 1)
        print("SPLIT_RUNTIME=" + json.dumps({"qgis": Qgis.QGIS_VERSION, "events": events, "features": rows}))
        layer.rollBack()


@unittest.skip("legacy dock-page navigation replaced by modeless popup runtime tests")
class IntegrationRuntimeTests(unittest.TestCase):
    def test_new_panel_with_pre_update_plugin_instance(self):
        layer, _ = memory_layer()
        plugin = engine(layer)
        del plugin._leave_survey
        # Reproduce the running old instance + lazily loaded new panel.
        panel = SurveyPanel(plugin)
        panel.reset_scope()
        buttons = {b.text(): b for b in panel.findChildren(QPushButton)}
        buttons['자료 새로고침'].click()
        self.assertEqual(panel.kind, 'sources')
        opened = []
        def close_import():
            dialog = APP.activeModalWidget()
            opened.append(isinstance(dialog, ImportDialog) and dialog.isVisible())
            if dialog is not None:
                dialog.reject()
        QTimer.singleShot(0, close_import)
        buttons['파일 가져오기'].click()
        self.assertEqual(opened, [True])
        buttons['시설물 화면으로 돌아가기'].click()
        plugin.render_state.assert_called_once()
        panel.close_service(); panel.deleteLater()

    def test_class_factory_reload_and_user_entry_points(self):
        from geoflow_connector import classFactory
        from geoflow_connector.app.state import State
        from qgis.gui import QgsMapCanvas
        window = QMainWindow(); window.resize(1100, 900)
        canvas = QgsMapCanvas(window); window.setCentralWidget(canvas)
        menu = window.menuBar().addMenu('GeoFlow')
        toolbar = window.addToolBar('Plugins')
        iface = Mock()
        iface.mainWindow.return_value = window
        iface.mapCanvas.return_value = canvas
        iface._geoflow_integration_events_v1 = None
        iface.addPluginToMenu.side_effect = lambda title, action: menu.addAction(action)
        iface.removePluginMenu.side_effect = lambda title, action: menu.removeAction(action)
        iface.addToolBarIcon.side_effect = toolbar.addAction
        iface.removeToolBarIcon.side_effect = toolbar.removeAction
        iface.addDockWidget.side_effect = window.addDockWidget
        iface.removeDockWidget.side_effect = window.removeDockWidget
        window.show()
        for cycle in range(2):
            plugin = classFactory(iface); plugin.initGui()
            action = plugin._survey_action
            self.assertTrue(action.isVisible()); self.assertTrue(action.isEnabled())
            self.assertFalse(action.icon().isNull())
            self.assertEqual(sum(a.objectName() == 'GeoFlowSurveyAction' for a in menu.actions()), 1)
            self.assertIn(action, toolbar.actions())
            plugin._ensure_ui(); plugin._ensure_ui()
            self.assertEqual(plugin.presentation.root.rail_layout.indexOf(plugin._survey_button), 2)
            self.assertIn(action, plugin.presentation.root.moreActionsButton.menu().actions())
            # Unauthenticated entry routes to login without making API requests.
            with patch.object(plugin, 'run') as login:
                action.trigger(); login.assert_called_once()
            client = Mock(base_url='https://example.invalid', session_user={})
            client.get_json.return_value = {'results': [{'id': SURVEY}]}
            plugin.dialog.client = plugin.active_client = client
            plugin.dialog.project_opened = True
            plugin.active_context = {'project_id': PROJECT, 'manifest': {}}
            # Facility rendering is unrelated to Survey navigation.
            plugin.work = QWidget(); plugin.work.shutdown = Mock()
            plugin.stack.addWidget(plugin.work)
            plugin._ensure_work = lambda: None
            plugin.state_manager.set(State.PROJECT_READY)
            plugin._survey_button.click(); APP.processEvents()
            panel = plugin._survey_panel
            self.assertIs(plugin.stack.currentWidget(), panel)
            self.assertTrue(plugin._survey_button.isVisible())
            self.assertTrue(panel.isVisible())
            buttons = {b.text(): b for b in panel.findChildren(QPushButton)}
            buttons['자료 새로고침'].click()
            self.assertEqual(panel.tree.topLevelItemCount(), 1)
            self.assertEqual(panel.kind, 'sources')
            opened = []
            def close_import():
                dialog = APP.activeModalWidget()
                opened.append(isinstance(dialog, ImportDialog) and dialog.isVisible())
                if dialog is not None:
                    dialog.reject()
            QTimer.singleShot(0, close_import)
            buttons['파일 가져오기'].click()
            self.assertEqual(opened, [True])
            plugin.render_state()
            self.assertIs(plugin.stack.currentWidget(), panel)
            buttons['시설물 화면으로 돌아가기'].click()
            self.assertIs(plugin.stack.currentWidget(), plugin.work)
            action.trigger()
            self.assertIs(plugin.stack.currentWidget(), panel)
            plugin.show_projects()
            self.assertIs(plugin.stack.currentWidget(), plugin.project_page)
            plugin._survey_button.click()
            self.assertFalse(plugin._project_selector_visible)
            plugin.dialog.project_opened = False
            plugin.integration_events.changed.emit()
            self.assertFalse(panel.isEnabled())
            self.assertTrue(action.isVisible()); self.assertTrue(action.isEnabled())
            plugin.active_context = None
            with patch.object(plugin, '_checkpoint_safely', return_value=(True, None)):
                plugin.unload()
            self.assertNotIn(action, menu.actions())
            self.assertNotIn(action, toolbar.actions())
            APP.processEvents()
        window.close(); window.deleteLater()

    def test_menu_opens_existing_dock_page_and_unloads(self):
        layer, _ = memory_layer()
        class Base:
            def __init__(self):
                self.__dict__.update(engine(layer).__dict__)
                self.window = QMainWindow()
                self.dock = QDockWidget(self.window)
                self.stack = QStackedWidget(); self.dock.setWidget(self.stack)
                root = loadUi(str(Path(__file__).resolve().parents[1] / 'ui/designer/main_dock.ui'))
                root.moreActionsButton.setMenu(QMenu(root.moreActionsButton))
                self.presentation = SimpleNamespace(root=root)
                self.integration_events = IntegrationEvents(self.window)
                self.iface.mainWindow = lambda: self.window
                for name in ("addPluginToMenu", "addToolBarIcon", "removePluginMenu", "removeToolBarIcon"):
                    setattr(self.iface, name, Mock())
            def initGui(self):
                pass
            def unload(self):
                pass
            def _ensure_ui(self):
                pass
            def _update_presentation(self):
                pass
        class Integrated(SurveyIntegrationMixin, Base):
            pass
        plugin = Integrated(); plugin.initGui()
        self.assertTrue(plugin._survey_action.isEnabled())
        plugin._survey_action.trigger()
        self.assertIs(plugin.stack.currentWidget(), plugin._survey_panel)
        plugin._survey_panel.resize(600, 850)
        # An actual QWidget render catches missing widgets/layout/runtime errors.
        self.assertFalse(plugin._survey_panel.grab().isNull())
        plugin.unload()
        plugin.iface.removePluginMenu.assert_called_once()
        self.assertIsNone(plugin._survey_panel)
        plugin.window.close(); plugin.window.deleteLater()


if __name__ == "__main__":
    print("QGIS_RUNTIME=" + Qgis.QGIS_VERSION)
    unittest.main()
