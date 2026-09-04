from __future__ import annotations

import datetime as dt
import os
import re

from qgis.PyQt.QtCore import QStandardPaths
from qgis.PyQt.QtWidgets import QAction
from qgis.core import QgsDefaultValue, QgsProject, QgsRectangle, QgsVectorLayer, Qgis

from .dialog import GeoFlowConnectorDialog


_SAFE_FILE_RE = re.compile(r"[^A-Za-z0-9_.-]+")
_DOMAIN_LABELS = {
    "COMMON": "공통",
    "WTL": "상수",
    "SWL": "하수",
    "ROAD": "도로",
}


class GeoFlowConnectorPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None
        self.active_context = None

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
                on_sync=self._sync_active_project,
            )
        self.dialog.show()
        self.dialog.raise_()
        self.dialog.activateWindow()

    @staticmethod
    def _safe_name(value: str) -> str:
        cleaned = _SAFE_FILE_RE.sub("_", str(value or "layer"))
        return cleaned.strip("._") or "layer"

    @staticmethod
    def _write_project_metadata(
        qgs_project: QgsProject,
        manifest: dict,
        project_id: str,
        project_code: str,
        package_path: str,
        sync_supported: bool,
    ):
        profile = manifest.get("profile") or {}
        qgs_project.writeEntry("GeoFlow", "managed", "1")
        qgs_project.writeEntry("GeoFlow", "project_id", project_id)
        qgs_project.writeEntry("GeoFlow", "project_code", project_code)
        qgs_project.writeEntry("GeoFlow", "profile_code", str(profile.get("code") or ""))
        qgs_project.writeEntry("GeoFlow", "manifest_version", str(manifest.get("manifest_version") or ""))
        qgs_project.writeEntry("GeoFlow", "package_path", package_path)
        qgs_project.writeEntry("GeoFlow", "sync_supported", "1" if sync_supported else "0")

    @staticmethod
    def _field_index(layer: QgsVectorLayer, name: str) -> int:
        try:
            return int(layer.fields().indexOf(name))
        except Exception:
            return -1

    @staticmethod
    def _configure_layer_fields(layer: QgsVectorLayer, layer_def: dict, project_id: str, can_write: bool) -> None:
        field_defs = {str(row.get("name") or ""): row for row in (layer_def.get("fields") or [])}

        if hasattr(layer, "setReadOnly"):
            layer.setReadOnly(not can_write)

        if not can_write:
            return

        id_idx = GeoFlowConnectorPlugin._field_index(layer, "id")
        if id_idx >= 0 and hasattr(layer, "setDefaultValueDefinition"):
            layer.setDefaultValueDefinition(id_idx, QgsDefaultValue("uuid()"))

        project_idx = GeoFlowConnectorPlugin._field_index(layer, "project_id")
        if project_idx >= 0 and hasattr(layer, "setDefaultValueDefinition"):
            escaped = project_id.replace("'", "''")
            layer.setDefaultValueDefinition(project_idx, QgsDefaultValue(f"'{escaped}'"))

        created_idx = GeoFlowConnectorPlugin._field_index(layer, "created_at")
        if created_idx >= 0 and hasattr(layer, "setDefaultValueDefinition"):
            layer.setDefaultValueDefinition(created_idx, QgsDefaultValue("now()"))

        updated_idx = GeoFlowConnectorPlugin._field_index(layer, "updated_at")
        if updated_idx >= 0 and hasattr(layer, "setDefaultValueDefinition"):
            layer.setDefaultValueDefinition(updated_idx, QgsDefaultValue("now()", True))

        try:
            config = layer.editFormConfig()
            if hasattr(config, "setReadOnly"):
                for name, meta in field_defs.items():
                    idx = GeoFlowConnectorPlugin._field_index(layer, name)
                    if idx < 0:
                        continue
                    if name in {"id", "project_id", "created_at", "updated_at"} or not bool(meta.get("editable", True)):
                        config.setReadOnly(idx, True)
                layer.setEditFormConfig(config)
        except Exception:
            pass

    @staticmethod
    def _domain_group(parent_group, domain: str, groups: dict):
        key = str(domain or "OTHER").upper()
        if key not in groups:
            groups[key] = parent_group.addGroup(_DOMAIN_LABELS.get(key, key or "기타"))
        return groups[key]

    def _materialize_project(self, manifest: dict, client) -> dict:
        transport = manifest.get("transport") or {}
        if transport.get("mode") != "server_gpkg_editable_snapshot":
            raise RuntimeError("지원하지 않는 GeoFlow QGIS transport입니다.")
        if transport.get("direct_postgis_credentials_exposed"):
            raise RuntimeError("안전하지 않은 DB credential manifest를 거부했습니다.")

        package_url = str(transport.get("package_url") or "")
        if not package_url:
            raise RuntimeError("GeoFlow GeoPackage URL이 없습니다.")

        project_def = manifest.get("project") or {}
        project_id = str(project_def.get("id") or "")
        project_code = str(project_def.get("code") or project_id[:8] or "PROJECT")
        if not project_id:
            raise RuntimeError("GeoFlow project id가 없습니다.")

        can_write = bool(transport.get("local_editing_supported") and transport.get("write_authorized"))
        sync_supported = bool(can_write and transport.get("sync_supported") and transport.get("sync_url"))

        app_root = QStandardPaths.writableLocation(QStandardPaths.AppDataLocation)
        project_dir = os.path.join(app_root, "GeoFlowConnector", "projects", self._safe_name(project_id))
        os.makedirs(project_dir, exist_ok=True)
        stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
        package_name = f"geoflow-{self._safe_name(project_code)}-{stamp}.gpkg"
        package_path = os.path.join(project_dir, package_name)

        raw = client.get_bytes(package_url)
        if not raw.startswith(b"SQLite format 3\x00"):
            raise RuntimeError("GeoFlow Server가 유효한 GeoPackage를 반환하지 않았습니다.")
        with open(package_path, "wb") as handle:
            handle.write(raw)

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
        domain_groups = {}

        loaded = 0
        combined_extent = None
        managed_layer_ids = []
        for layer_def in manifest.get("layers") or []:
            physical_name = str(layer_def.get("physical_name") or "")
            standard_name = str(layer_def.get("standard_name") or physical_name.upper())
            if not physical_name:
                continue

            layer = QgsVectorLayer(
                f"{package_path}|layername={physical_name}",
                layer_def.get("label") or standard_name,
                "ogr",
            )
            if not layer.isValid():
                raise RuntimeError(f"{standard_name}: GeoPackage 레이어 생성에 실패했습니다.")

            self._configure_layer_fields(layer, layer_def, project_id, can_write)
            layer.setCustomProperty("geoflow/managed", True)
            layer.setCustomProperty("geoflow/project_id", project_id)
            layer.setCustomProperty("geoflow/standard_name", standard_name)
            layer.setCustomProperty("geoflow/package_path", package_path)
            layer.setCustomProperty("geoflow/local_editing", can_write)
            layer.setCustomProperty("geoflow/sync_supported", sync_supported)
            layer.setCustomProperty("geoflow/server_row_count", layer_def.get("row_count", -1))

            qgs_project.addMapLayer(layer, False)
            self._domain_group(group, layer_def.get("domain"), domain_groups).addLayer(layer)
            managed_layer_ids.append(layer.id())
            loaded += 1

            if layer.featureCount() > 0:
                extent = layer.extent()
                if not extent.isEmpty():
                    if combined_extent is None:
                        combined_extent = QgsRectangle(extent)
                    else:
                        combined_extent.combineExtentWith(extent)

        self._write_project_metadata(
            qgs_project,
            manifest,
            project_id,
            project_code,
            package_path,
            sync_supported,
        )
        self.active_context = {
            "project_id": project_id,
            "project_code": project_code,
            "package_path": package_path,
            "sync_url": str(transport.get("sync_url") or ""),
            "sync_supported": sync_supported,
            "layer_ids": managed_layer_ids,
        }

        if combined_extent is not None and not combined_extent.isEmpty():
            self.iface.mapCanvas().setExtent(combined_extent)
            self.iface.mapCanvas().refresh()

        mode_label = "로컬 편집 가능" if can_write else "읽기 전용"
        sync_label = "서버 동기화 가능" if sync_supported else "서버 동기화 비활성"
        size_mb = len(raw) / (1024 * 1024)
        self.iface.messageBar().pushMessage(
            "GeoFlow",
            (
                f"{project_code}: GeoPackage 1회 다운로드 · 레이어 {loaded}개 · "
                f"{mode_label} · {sync_label} · {size_mb:.2f} MB"
            ),
            level=Qgis.Success,
            duration=8,
        )
        return {"loaded": loaded, "sync_supported": sync_supported}

    def _commit_active_edits(self) -> None:
        context = self.active_context or {}
        package_path = str(context.get("package_path") or "")
        if not package_path:
            raise RuntimeError("동기화할 GeoFlow 프로젝트가 열려 있지 않습니다.")

        qgs_project = QgsProject.instance()
        for layer_id in context.get("layer_ids") or []:
            layer = qgs_project.mapLayer(layer_id)
            if layer is None:
                continue
            if layer.isEditable():
                if not layer.commitChanges():
                    errors = "; ".join(layer.commitErrors()) if hasattr(layer, "commitErrors") else ""
                    raise RuntimeError(
                        f"{layer.name()}: 로컬 편집 저장에 실패했습니다.{(' ' + errors) if errors else ''}"
                    )

    def _sync_active_project(self, client) -> dict:
        context = self.active_context or {}
        if not context.get("sync_supported"):
            raise RuntimeError("현재 프로젝트는 GeoFlow 서버 동기화가 활성화되어 있지 않습니다.")
        package_path = str(context.get("package_path") or "")
        sync_url = str(context.get("sync_url") or "")
        project_id = str(context.get("project_id") or "")
        if not package_path or not sync_url or not project_id:
            raise RuntimeError("GeoFlow 동기화 컨텍스트가 불완전합니다.")

        self._commit_active_edits()
        result = client.post_file_json(sync_url, package_path, field_name="package")

        # Re-materialize immediately so the local baseline matches the new
        # authoritative server updated_at values for the next edit/sync cycle.
        fresh_manifest = client.get_json(f"/gis/projects/{project_id}/api/qgis-manifest/")
        self._materialize_project(fresh_manifest, client)

        self.iface.messageBar().pushMessage(
            "GeoFlow",
            (
                f"동기화 완료 · 신규 {int(result.get('created') or 0)} · "
                f"수정 {int(result.get('updated') or 0)} · 삭제 {int(result.get('deleted') or 0)}"
            ),
            level=Qgis.Success,
            duration=8,
        )
        return result
