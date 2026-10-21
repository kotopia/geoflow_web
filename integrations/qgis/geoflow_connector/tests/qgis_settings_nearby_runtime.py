"""QGIS 4.2.2 runtime checks for project settings and nearby consumers."""
import math
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import QApplication, QMainWindow
from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsPointXY, QgsProject, QgsVectorLayer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geoflow_connector.services.depth import DepthService
from geoflow_connector.services.settings import GeoFlowSettingsService
from geoflow_connector.ui.settings_dialog import GeoFlowSettingsDialog


APP = QApplication.instance() or QgsApplication([], False)
if isinstance(APP, QgsApplication):
    APP.initQgis()

settings_path = str(Path(tempfile.mkdtemp()) / "geoflow-settings.ini")
backend = QSettings(settings_path, QSettings.Format.IniFormat)
logs = []
window = QMainWindow()
plugin = SimpleNamespace(
    active_context={"project_id": "project-a"},
    active_client=SimpleNamespace(base_url="https://example.test"),
    iface=SimpleNamespace(mainWindow=lambda: window),
    integration_state=lambda: {
        "ready": True, "project_id": plugin.active_context["project_id"],
        "project_name": plugin.active_context["project_id"],
    },
    log=logs.append,
)
service = GeoFlowSettingsService(plugin, backend)
assert service.snapshot() == {
    "default_radius_m": 2.0,
    "depth_radius_m": 2.0,
    "manhole_radius_m": 2.0,
    "nearest_first": True,
    "show_nearby_button": True,
    "show_previous_button": True,
    "show_field_action_buttons": True,
}

survey = QgsVectorLayer(
    "Point?crs=EPSG:4326&field=id:string&field=code:string&field=raw_z:double",
    "survey", "memory",
)
survey.setCustomProperty("geoflow/standard_name", "SURVEY")
origin = QgsPointXY(127.0, 36.0)
delta_lon = 8.0 / (111320.0 * math.cos(math.radians(origin.y())))
for object_id, code, raw_z, point in (
    ("source", "S", 20.0, origin),
    ("h-8m", "H", 22.0, QgsPointXY(origin.x() + delta_lon, origin.y())),
):
    feature = QgsFeature(survey.fields())
    feature["id"], feature["code"], feature["raw_z"] = object_id, code, raw_z
    feature.setGeometry(QgsGeometry.fromPointXY(point))
    assert survey.dataProvider().addFeature(feature)
plugin._managed_layers = lambda: [survey]
depth = DepthService(plugin, settings=service, project=QgsProject.instance())
source = {"id": "source"}

service.save_nearby(
    default_radius_m=10, depth_radius_m=5, manhole_radius_m=5,
    nearest_first=True,
)
five = depth.calculate_survey_point(source)
assert not five["ok"] and five["reason"] == "no_height_candidate", five

# Project scopes switch immediately and remain independent.
plugin.active_context = {"project_id": "project-b"}
service.save_nearby(
    default_radius_m=10, depth_radius_m=15, manhole_radius_m=7,
    nearest_first=False,
)
assert depth.radius_m == 15.0
plugin.active_context = {"project_id": "project-a"}
assert depth.radius_m == 5.0

# No service recreation: the already-open consumer must observe the new value.
service.save_nearby(
    default_radius_m=10, depth_radius_m=10, manhole_radius_m=5,
    nearest_first=True,
)
ten = depth.calculate_survey_point(source)
assert ten["ok"] and ten["depth"] == 2.0, ten
assert 7.5 < ten["distance_m"] < 8.5, ten

service.save_nearby(
    default_radius_m=20, depth_radius_m=20, manhole_radius_m=5,
    nearest_first=True,
)
assert depth.radius_m == 20.0
twenty = depth.calculate_survey_point(source)
assert twenty["ok"] and twenty["depth"] == 2.0, twenty
plugin.active_context = {"project_id": "project-b"}
assert depth.radius_m == 15.0
plugin.active_context = {"project_id": "project-a"}

dialog = GeoFlowSettingsDialog(plugin, settings_service=service)
assert [dialog.settingsTabs.tabText(i) for i in range(dialog.settingsTabs.count())] == [
    "주변값", "도형", "폼",
]
assert not dialog.upperArcSpin.isEnabled() and not dialog.lowerArcSpin.isEnabled()
dialog.show()
APP.processEvents()
artifact = Path(__file__).resolve().parents[1] / "test_artifacts" / "settings_qgis422.png"
artifact.parent.mkdir(exist_ok=True)
assert dialog.grab().save(str(artifact))
dialog.close()

assert any(row.startswith("[SETTINGS]") for row in logs)
assert "[SETTINGS] nearby.depth_radius_m=20.0" in logs
assert any(row.startswith("[NEARBY] function=depth") for row in logs)
print("QGIS_SETTINGS_NEARBY_RUNTIME_OK")
