from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3

from qgis.PyQt.QtCore import QStandardPaths, QTimer
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
_SYSTEM_FIELDS = {
    "id",
    "project_id",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
}


class GeoFlowConnectorPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None
        self.active_context = None
        self.active_client = None
        self._sync_in_progress = False
        self._suppress_auto_sync = False
        self._auto_sync_timer = QTimer()
        self._auto_sync_timer.setSingleShot(True)
        self._auto_sync_timer.setInterval(700)
        self._auto_sync_timer.timeout.connect(self._run_auto_sync)

    def initGui(self):
        self.action = QAction("GeoFlow Connector", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("GeoFlow", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        self._auto_sync_timer.stop()
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
        qgs_project.writeEntry("GeoFlow", "sync_strategy", "last_successful_server_write_wins")

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

    @staticmethod
    def _extract_gpkg_wkb(blob):
        if blob is None:
            return None
        raw = bytes(blob)
        if len(raw) < 8 or raw[:2] != b"GP":
            raise RuntimeError("GeoPackage geometry blob이 올바르지 않습니다.")
        flags = raw[3]
        envelope_code = (flags >> 1) & 0x07
        envelope_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
        if envelope_code not in envelope_sizes:
            raise RuntimeError("지원하지 않는 GeoPackage geometry envelope입니다.")
        offset = 8 + envelope_sizes[envelope_code]
        return raw[offset:] if len(raw) > offset else None

    @staticmethod
    def _json_safe(value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, (bytes, bytearray, memoryview)):
            return {"__bytes__": bytes(value).hex()}
        if isinstance(value, dict):
            return {
                str(key): GeoFlowConnectorPlugin._json_safe(item)
                for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(value, (list, tuple)):
            return [GeoFlowConnectorPlugin._json_safe(item) for item in value]
        return str(value)

    @staticmethod
    def _content_hash(attributes: dict, geometry_wkb, editable_names) -> str:
        names = sorted({str(name) for name in editable_names})
        payload = {
            "attributes": {
                name: GeoFlowConnectorPlugin._json_safe(attributes.get(name))
                for name in names
            },
            "geometry_wkb": bytes(geometry_wkb).hex() if geometry_wkb is not None else None,
        }
        encoded = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    @staticmethod
    def _refresh_local_baseline(package_path: str, manifest: dict) -> None:
        conn = sqlite3.connect(package_path, timeout=30)
        try:
            conn.execute("PRAGMA busy_timeout=30000")
            columns = {
                row[1]
                for row in conn.execute("PRAGMA table_info('_geoflow_baseline')").fetchall()
            }
            if "content_hash" not in columns:
                raise RuntimeError("GeoFlow package baseline hash가 없습니다. 프로젝트를 다시 여세요.")

            for layer_def in manifest.get("layers") or []:
                physical_name = str(layer_def.get("physical_name") or "")
                if not physical_name:
                    continue
                fields = layer_def.get("fields") or []
                field_names = [str(row.get("name") or "") for row in fields if row.get("name")]
                editable_names = [
                    str(row.get("name"))
                    for row in fields
                    if row.get("name")
                    and bool(row.get("editable", True))
                    and str(row.get("name")) not in _SYSTEM_FIELDS
                ]
                quoted_fields = ", ".join(f'"{name}"' for name in field_names)
                rows = conn.execute(
                    f'SELECT fid, {quoted_fields}, "geom" FROM "{physical_name}"'
                ).fetchall()
                conn.execute(
                    "DELETE FROM _geoflow_baseline WHERE layer_name=?",
                    (physical_name,),
                )
                baseline_rows = []
                for row in rows:
                    fid = int(row[0])
                    attrs = dict(zip(field_names, row[1:-1]))
                    object_id = str(attrs.get("id") or "")
                    if not object_id:
                        continue
                    wkb = GeoFlowConnectorPlugin._extract_gpkg_wkb(row[-1])
                    digest = GeoFlowConnectorPlugin._content_hash(
                        attrs,
                        wkb,
                        editable_names,
                    )
                    baseline_rows.append(
                        (physical_name, object_id, fid, None, digest)
                    )
                if baseline_rows:
                    conn.executemany(
                        """
                        INSERT INTO _geoflow_baseline(
                            layer_name, object_id, local_fid, source_updated_at, content_hash
                        ) VALUES (?,?,?,?,?)
                        """,
                        baseline_rows,
                    )
            conn.commit()
        finally:
            conn.close()

    def _managed_layers(self):
        context = self.active_context or {}
        project = QgsProject.instance()
        result = []
        for layer_id in context.get("layer_ids") or []:
            layer = project.mapLayer(layer_id)
            if layer is not None:
                result.append(layer)
        return result

    def _schedule_auto_sync(self, *args):
        if self._sync_in_progress or self._suppress_auto_sync:
            return
        context = self.active_context or {}
        if not context.get("sync_supported") or self.active_client is None:
            return
        self._auto_sync_timer.start()

    def _run_auto_sync(self):
        if self._sync_in_progress or self.active_client is None:
            return
        for layer in self._managed_layers():
            try:
                if layer.isModified():
                    # Another managed layer still has unsaved edits. Wait for its
                    # save event so one consistent package is sent.
                    self._auto_sync_timer.start()
                    return
            except Exception:
                pass
        try:
            self._sync_active_project(self.active_client, automatic=True)
        except Exception as exc:
            self.iface.messageBar().pushMessage(
                "GeoFlow 자동 동기화 실패",
                str(exc),
                level=Qgis.Warning,
                duration=10,
            )

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

            if sync_supported and hasattr(layer, "afterCommitChanges"):
                try:
                    layer.afterCommitChanges.connect(self._schedule_auto_sync)
                except Exception:
                    pass

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
            "manifest": manifest,
        }
        self.active_client = client

        if combined_extent is not None and not combined_extent.isEmpty():
            self.iface.mapCanvas().setExtent(combined_extent)
            self.iface.mapCanvas().refresh()

        mode_label = "로컬 편집 가능" if can_write else "읽기 전용"
        sync_label = "저장 시 자동 동기화" if sync_supported else "서버 동기화 비활성"
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

        for layer in self._managed_layers():
            if layer.isEditable():
                if not layer.commitChanges():
                    errors = "; ".join(layer.commitErrors()) if hasattr(layer, "commitErrors") else ""
                    raise RuntimeError(
                        f"{layer.name()}: 로컬 편집 저장에 실패했습니다.{(' ' + errors) if errors else ''}"
                    )

    def _sync_active_project(self, client, automatic: bool = False) -> dict:
        context = self.active_context or {}
        if not context.get("sync_supported"):
            raise RuntimeError("현재 프로젝트는 GeoFlow 서버 동기화가 활성화되어 있지 않습니다.")
        package_path = str(context.get("package_path") or "")
        sync_url = str(context.get("sync_url") or "")
        if not package_path or not sync_url:
            raise RuntimeError("GeoFlow 동기화 컨텍스트가 불완전합니다.")
        if self._sync_in_progress:
            return {"ok": True, "created": 0, "updated": 0, "deleted": 0, "total": 0}

        self._sync_in_progress = True
        self._suppress_auto_sync = True
        try:
            if not automatic:
                self._commit_active_edits()
            result = client.post_file_json(sync_url, package_path, field_name="package")
            self._refresh_local_baseline(package_path, context.get("manifest") or {})
        finally:
            self._suppress_auto_sync = False
            self._sync_in_progress = False

        created = int(result.get("created") or 0)
        updated = int(result.get("updated") or 0)
        deleted = int(result.get("deleted") or 0)
        if created or updated or deleted:
            prefix = "자동 동기화 완료" if automatic else "동기화 완료"
            self.iface.messageBar().pushMessage(
                "GeoFlow",
                f"{prefix} · 신규 {created} · 수정 {updated} · 삭제 {deleted}",
                level=Qgis.Success,
                duration=6,
            )
        return result
