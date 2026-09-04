from __future__ import annotations

import json
import os
import re

from qgis.PyQt.QtCore import QStandardPaths, QVariant
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsField, QgsProject, QgsRectangle, QgsVectorLayer, Qgis

from .dialog import GeoFlowConnectorDialog


_SAFE_FILE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


class GeoFlowConnectorPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None

    def initGui(self):
        self.action = QAction("GeoFlow Connector", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("GeoFlow", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        if self.action is not None:
            self.iface.removePluginMenu("GeoFlow", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None

    def run(self):
        if self.dialog is None:
            self.dialog = GeoFlowConnectorDialog(
                self.iface.mainWindow(),
                on_open_project=self._materialize_project,
            )
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    @staticmethod
    def _safe_name(value: str) -> str:
        cleaned = _SAFE_FILE_RE.sub("_", str(value or "layer"))
        return cleaned.strip("._") or "layer"

    @staticmethod
    def _memory_layer(layer_def: dict) -> QgsVectorLayer:
        geometry = str(layer_def.get("geometry_kind") or "").upper()
        uri_geometry = {
            "POINT": "Point",
            "LINE": "LineString",
            "POLYGON": "Polygon",
        }.get(geometry, "GeometryCollection")
        layer = QgsVectorLayer(
            f"{uri_geometry}?crs=EPSG:4326",
            layer_def.get("label") or layer_def.get("standard_name") or "GeoFlow",
            "memory",
        )
        provider = layer.dataProvider()
        provider.addAttributes(
            [
                QgsField("id", QVariant.String),
                QgsField("layer", QVariant.String),
            ]
        )
        layer.updateFields()
        return layer

    @staticmethod
    def _write_project_metadata(qgs_project: QgsProject, manifest: dict, project_id: str, project_code: str):
        """Persist lightweight GeoFlow project metadata using QgsProject's supported API."""
        profile = manifest.get("profile") or {}
        qgs_project.writeEntry("GeoFlow", "managed", "1")
        qgs_project.writeEntry("GeoFlow", "project_id", project_id)
        qgs_project.writeEntry("GeoFlow", "project_code", project_code)
        qgs_project.writeEntry("GeoFlow", "profile_code", str(profile.get("code") or ""))
        qgs_project.writeEntry(
            "GeoFlow",
            "manifest_version",
            str(manifest.get("manifest_version") or ""),
        )

    def _materialize_project(self, manifest: dict, client) -> int:
        transport = manifest.get("transport") or {}
        if transport.get("mode") != "server_geojson_snapshot":
            raise RuntimeError("지원하지 않는 GeoFlow QGIS transport입니다.")
        if transport.get("direct_postgis_credentials_exposed"):
            raise RuntimeError("안전하지 않은 DB credential manifest를 거부했습니다.")

        project_def = manifest.get("project") or {}
        project_id = str(project_def.get("id") or "")
        project_code = str(project_def.get("code") or project_id[:8] or "PROJECT")
        if not project_id:
            raise RuntimeError("GeoFlow project id가 없습니다.")

        qgs_project = QgsProject.instance()
        root = qgs_project.layerTreeRoot()
        group_name = f"GeoFlow · {project_code}"
        old_group = root.findGroup(group_name)
        if old_group is not None:
            old_layer_ids = [node.layerId() for node in old_group.findLayers()]
            if old_layer_ids:
                qgs_project.removeMapLayers(old_layer_ids)
            root.removeChildNode(old_group)
        group = root.addGroup(group_name)

        temp_root = QStandardPaths.writableLocation(QStandardPaths.TempLocation)
        project_dir = os.path.join(temp_root, "GeoFlow", self._safe_name(project_id))
        os.makedirs(project_dir, exist_ok=True)

        loaded = 0
        fetched = 0
        skipped_empty = 0
        combined_extent = None
        for layer_def in manifest.get("layers") or []:
            standard_name = str(layer_def.get("standard_name") or "")
            snapshot_url = layer_def.get("snapshot_url")
            if not standard_name or not snapshot_url:
                continue

            row_count = layer_def.get("row_count")
            if row_count == 0 and not layer_def.get("snapshot_required", False):
                features = []
                layer = self._memory_layer(layer_def)
                skipped_empty += 1
            else:
                raw = client.get_bytes(snapshot_url)
                fetched += 1
                try:
                    payload = json.loads(raw.decode("utf-8"))
                except (UnicodeDecodeError, json.JSONDecodeError):
                    raise RuntimeError(f"{standard_name}: GeoJSON 응답을 해석할 수 없습니다.") from None

                meta = payload.get("meta") if isinstance(payload, dict) else None
                if isinstance(meta, dict) and meta.get("truncated"):
                    raise RuntimeError(
                        f"{standard_name}: 서버 snapshot 한도({meta.get('limit')})를 초과했습니다. "
                        "불완전한 QGIS 프로젝트를 만들지 않습니다."
                    )
                features = payload.get("features") if isinstance(payload, dict) else None
                if not isinstance(features, list):
                    raise RuntimeError(f"{standard_name}: FeatureCollection이 아닙니다.")

                if features:
                    file_name = self._safe_name(standard_name.lower()) + ".geojson"
                    file_path = os.path.join(project_dir, file_name)
                    with open(file_path, "wb") as handle:
                        handle.write(raw)
                    layer = QgsVectorLayer(
                        file_path,
                        layer_def.get("label") or standard_name,
                        "ogr",
                    )
                else:
                    layer = self._memory_layer(layer_def)

            if not layer.isValid():
                raise RuntimeError(f"{standard_name}: QGIS 레이어 생성에 실패했습니다.")

            if hasattr(layer, "setReadOnly"):
                layer.setReadOnly(True)
            layer.setCustomProperty("geoflow/managed", True)
            layer.setCustomProperty("geoflow/project_id", project_id)
            layer.setCustomProperty("geoflow/standard_name", standard_name)
            layer.setCustomProperty("geoflow/snapshot_url", snapshot_url)
            layer.setCustomProperty("geoflow/snapshot_editable", False)
            layer.setCustomProperty("geoflow/server_row_count", row_count if row_count is not None else -1)

            qgs_project.addMapLayer(layer, False)
            group.addLayer(layer)
            loaded += 1

            if features:
                extent = layer.extent()
                if not extent.isEmpty():
                    if combined_extent is None:
                        combined_extent = QgsRectangle(extent)
                    else:
                        combined_extent.combineExtentWith(extent)

        self._write_project_metadata(qgs_project, manifest, project_id, project_code)

        if combined_extent is not None and not combined_extent.isEmpty():
            self.iface.mapCanvas().setExtent(combined_extent)
            self.iface.mapCanvas().refresh()

        self.iface.messageBar().pushMessage(
            "GeoFlow",
            (
                f"{project_code}: QGIS snapshot 레이어 {loaded}개 구성 · "
                f"다운로드 {fetched}개 · 빈 레이어 요청 생략 {skipped_empty}개"
            ),
            level=Qgis.Success,
            duration=7,
        )
        return loaded
