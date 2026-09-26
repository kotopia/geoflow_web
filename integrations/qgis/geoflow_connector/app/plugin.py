# 제목: app/plugin.py
# 기능: 프로젝트 materialize, 레이어 생성, 변경 수집, 로컬 저장 후 동기화 엔진
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
import uuid

from qgis.PyQt.QtCore import QSettings, QStandardPaths, QTimer
try:
    from qgis.PyQt.QtGui import QAction
except ImportError:
    from qgis.PyQt.QtWidgets import QAction
from qgis.core import (
    QgsDefaultValue,
    QgsFeature,
    QgsFeatureRequest,
    QgsGeometry,
    QgsProject,
    QgsRectangle,
    QgsVectorLayer,
    Qgis,
)

from ..sync.queue import acknowledge_outbox, ensure_changeset_tables, outbox_count, pending_count, prepare_outbox, queue_change, read_last_applied_revision, repair_uuid_exists_outbox, write_last_applied_revision
from ..api.client import GeoFlowChangesetConflict
from ..layers.model import DOMAIN_LABELS as _DOMAIN_LABELS, SYSTEM_FORM_FIELDS as _SYSTEM_FIELDS


_SAFE_FILE_RE = re.compile(r"[^A-Za-z0-9_.-]+")


# ============================================================
# 프로젝트 materialize와 로컬 편집·동기화 엔진
# ============================================================
class GeoFlowConnectorPlugin:
    def __init__(self, iface):
        self.iface = iface
        self.action = None
        self.dialog = None
        self.active_context = None
        self.active_client = None
        self._sync_in_progress = False
        self._suppress_auto_sync = False
        self._captured_changes: dict[str, list[dict]] = {}
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
        self._captured_changes.clear()
        if self.action is not None:
            self.iface.removePluginMenu("GeoFlow", self.action)
            self.iface.removeToolBarIcon(self.action)
            self.action.deleteLater()
            self.action = None


    @staticmethod
    def _safe_name(value: str) -> str:
        cleaned = _SAFE_FILE_RE.sub("_", str(value or "layer"))
        return cleaned.strip("._") or "layer"

    @staticmethod
    def _app_data_location() -> str:
        """Return the per-user app-data directory across Qt5/Qt6."""
        standard_location = getattr(QStandardPaths, "StandardLocation", None)
        if standard_location is not None and hasattr(standard_location, "AppDataLocation"):
            enum_value = standard_location.AppDataLocation
        else:
            enum_value = getattr(QStandardPaths, "AppDataLocation")
        return QStandardPaths.writableLocation(enum_value)

    @staticmethod
    def _client_id() -> str:
        settings = QSettings()
        key = "GeoFlowConnector/client_id"
        value = str(settings.value(key, "") or "")
        try:
            return str(uuid.UUID(value))
        except (ValueError, TypeError, AttributeError):
            value = str(uuid.uuid4())
            settings.setValue(key, value)
            return value

    @staticmethod
    def _write_project_metadata(
        qgs_project: QgsProject,
        manifest: dict,
        project_id: str,
        project_code: str,
        package_path: str,
        sync_supported: bool,
        changeset_supported: bool,
    ):
        definition = manifest.get("definition") or {}
        qgs_project.writeEntry("GeoFlow", "managed", "1")
        qgs_project.writeEntry("GeoFlow", "project_id", project_id)
        qgs_project.writeEntry("GeoFlow", "project_code", project_code)
        qgs_project.writeEntry("GeoFlow", "definition_version", str(definition.get("version") or ""))
        qgs_project.writeEntry("GeoFlow", "definition_revision", str(definition.get("revision") or ""))
        qgs_project.writeEntry("GeoFlow", "photo_policy_revision", str(manifest.get("photo_policy_revision") or ""))
        qgs_project.writeEntry("GeoFlow", "manifest_version", str(manifest.get("manifest_version") or ""))
        qgs_project.writeEntry("GeoFlow", "package_path", package_path)
        qgs_project.writeEntry("GeoFlow", "sync_supported", "1" if sync_supported else "0")
        qgs_project.writeEntry(
            "GeoFlow",
            "sync_strategy",
            "changeset_v1" if changeset_supported else "gpkg_diff_fallback",
        )

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
                    if name in _SYSTEM_FIELDS or not bool(meta.get("editable", True)):
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

    def _layer_def(self, layer: QgsVectorLayer) -> dict:
        standard_name = str(layer.customProperty("geoflow/standard_name", "") or "")
        for row in ((self.active_context or {}).get("manifest") or {}).get("layers") or []:
            if str(row.get("standard_name") or "") == standard_name:
                return row
        return {}

    @staticmethod
    def _feature_object_id(layer: QgsVectorLayer, fid: int, package_path: str, physical_name: str) -> str:
        feature = layer.getFeature(fid)
        if feature is not None and feature.isValid():
            try:
                value = feature["id"]
                if value:
                    return str(uuid.UUID(str(value)))
            except Exception:
                pass
        conn = sqlite3.connect(package_path, timeout=30)
        try:
            row = conn.execute(
                f'SELECT "id" FROM "{physical_name}" WHERE fid=?',
                (int(fid),),
            ).fetchone()
        finally:
            conn.close()
        if not row or not row[0]:
            return ""
        return str(uuid.UUID(str(row[0])))

    def _capture_layer_changes(self, layer_id: str, *args) -> None:
        if self._suppress_auto_sync:
            return
        context = self.active_context or {}
        if not context.get("changeset_supported"):
            return
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is None:
            return
        buffer = layer.editBuffer()
        if buffer is None:
            return

        package_path = str(context.get("package_path") or "")
        physical_name = str(layer.customProperty("geoflow/physical_name", "") or "")
        standard_name = str(layer.customProperty("geoflow/standard_name", "") or "")
        layer_def = self._layer_def(layer)
        editable_names = {
            str(row.get("name"))
            for row in (layer_def.get("fields") or [])
            if row.get("name")
            and bool(row.get("editable", True))
            and str(row.get("name")) not in _SYSTEM_FIELDS
        }

        added = dict(buffer.addedFeatures() or {})
        changed_attrs = dict(buffer.changedAttributeValues() or {})
        changed_geoms = dict(buffer.changedGeometries() or {})
        deleted = set(buffer.deletedFeatureIds() or set())
        added_ids = set(added)
        cancelled = added_ids & deleted
        changes: dict[str, dict] = {}

        for fid, feature in added.items():
            if fid in cancelled:
                continue
            try:
                object_id = str(uuid.UUID(str(feature["id"])))
            except Exception:
                continue
            attrs = {}
            for name in editable_names:
                idx = self._field_index(layer, name)
                if idx < 0:
                    continue
                value = feature.attribute(idx)
                if value is not None:
                    attrs[name] = self._json_safe(value)
            geometry = feature.geometry()
            if geometry is None or geometry.isEmpty():
                continue
            changes[object_id] = {
                "action": "create",
                "layer": standard_name,
                "id": object_id,
                "attributes": attrs,
                "geometry_wkb": bytes(geometry.asWkb()).hex(),
            }

        existing_fids = (set(changed_attrs) | set(changed_geoms)) - added_ids - deleted
        for fid in existing_fids:
            object_id = self._feature_object_id(layer, fid, package_path, physical_name)
            if not object_id:
                continue
            attrs = {}
            for field_index, value in (changed_attrs.get(fid) or {}).items():
                try:
                    name = str(layer.fields().at(int(field_index)).name())
                except Exception:
                    continue
                if name in editable_names:
                    attrs[name] = self._json_safe(value)
            change = {
                "action": "update",
                "layer": standard_name,
                "id": object_id,
                "attributes": attrs,
            }
            if fid in changed_geoms:
                geometry = changed_geoms[fid]
                if geometry is not None and not geometry.isEmpty():
                    change["geometry_wkb"] = bytes(geometry.asWkb()).hex()
            if attrs or "geometry_wkb" in change:
                changes[object_id] = change

        for fid in deleted - added_ids:
            object_id = self._feature_object_id(layer, fid, package_path, physical_name)
            if not object_id:
                continue
            changes[object_id] = {
                "action": "delete",
                "layer": standard_name,
                "id": object_id,
            }

        self._captured_changes[layer_id] = list(changes.values())

    def _after_layer_commit(self, layer_id: str, *args) -> None:
        if self._suppress_auto_sync:
            self._captured_changes.pop(layer_id, None)
            return
        context = self.active_context or {}
        package_path = str(context.get("package_path") or "")
        if context.get("changeset_supported") and package_path:
            changes = self._captured_changes.pop(layer_id, [])
            try:
                for change in changes:
                    queue_change(
                        package_path,
                        layer=change["layer"],
                        object_id=change["id"],
                        action=change["action"],
                        attributes=change.get("attributes") or {},
                        geometry_wkb=change.get("geometry_wkb"),
                    )
            except Exception as exc:
                self.iface.messageBar().pushMessage(
                    "GeoFlow 로컬 Changeset 저장 실패",
                    str(exc),
                    level=Qgis.Warning,
                    duration=10,
                )
                return
        self._schedule_auto_sync()

    def _schedule_auto_sync(self, *args):
        if self._sync_in_progress or self._suppress_auto_sync:
            return
        context = self.active_context or {}
        if not (
            context.get("changeset_supported") or context.get("fallback_sync_supported")
        ) or self.active_client is None:
            return
        self._auto_sync_timer.start()

    def _run_auto_sync(self):
        if self._sync_in_progress or self.active_client is None:
            return
        for layer in self._managed_layers():
            try:
                if layer.isModified():
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

    def current_user_context(self) -> dict:
        context = self.active_context or {}
        client = getattr(self.dialog, "client", None) if self.dialog is not None else None
        info = context.get("user") or getattr(client, "session_user", {}) or {}
        if not isinstance(info, dict) or not info:
            return {}
        return {
            "user_id": str(info.get("user_id") or ""),
            "display_name": str(info.get("display_name") or info.get("name") or ""),
            "worker_id": str(info.get("worker_id") or ""),
            "worker_name": str(info.get("worker_name") or ""),
            "employee_id": str(info.get("employee_id") or ""),
            "worker_link_status": str(info.get("worker_link_status") or "unknown"),
        }

    def current_project_context(self) -> dict:
        context = self.active_context or {}
        project = ((context.get("manifest") or {}).get("project") or {})
        return {
            "project_id": str(context.get("project_id") or project.get("id") or ""),
            "project_name": str(project.get("name") or context.get("project_code") or ""),
            "project_code": str(project.get("project_code") or project.get("code") or ""),
            "package_path": str(context.get("package_path") or ""),
        }


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

    @staticmethod
    def _delta_value(value):
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        return value

    @staticmethod
    def _geometry_from_hex(value: str | None):
        if not value:
            return None
        geometry = QgsGeometry()
        result = geometry.fromWkb(bytes.fromhex(str(value)))
        if result is False:
            raise RuntimeError("GeoFlow Delta geometry를 읽을 수 없습니다.")
        return geometry



    def _pull_and_apply_delta(self, client) -> int:
        context = self.active_context or {}
        package_path = str(context.get("package_path") or "")
        delta_url = str(context.get("delta_url") or "")
        if not package_path or not delta_url:
            return 0
        total = 0
        cursor = read_last_applied_revision(package_path)
        while True:
            separator = "&" if "?" in delta_url else "?"
            page = client.get_json(
                f"{delta_url}{separator}since={cursor}&limit=1000"
            )
            if page.get("snapshot_required"):
                raise RuntimeError(
                    "서버 Delta 보존 범위를 벗어났습니다. 최신 Snapshot을 다시 열어야 합니다."
                )
            changes = page.get("changes") or []
            if changes:
                self._apply_delta_page(changes)
                total += len(changes)
                cursor = int(page.get("next_revision") or cursor)
                write_last_applied_revision(package_path, cursor)
            if not page.get("has_more"):
                break
            if not changes:
                raise RuntimeError("GeoFlow Delta cursor가 전진하지 않았습니다.")
        return total

    def _sync_changesets(self, client) -> dict:
        context = self.active_context or {}
        package_path = str(context.get("package_path") or "")
        changeset_url = str(context.get("changeset_url") or "")
        client_id = str(context.get("client_id") or "")
        if not package_path or not changeset_url or not client_id:
            raise RuntimeError("GeoFlow Changeset 컨텍스트가 불완전합니다.")

        totals = {"created": 0, "updated": 0, "deleted": 0, "total": 0}
        while True:
            prepared = prepare_outbox(package_path, client_id=client_id)
            if prepared is None:
                break
            changeset_id, payload = prepared
            try:
                result = client.post_json(changeset_url, payload)
            except GeoFlowChangesetConflict as exc:
                repaired = repair_uuid_exists_outbox(
                    package_path,
                    changeset_id,
                    exc.conflicts,
                )
                if repaired is None:
                    raise
                changeset_id, payload = repaired
                self.iface.messageBar().pushMessage(
                    "GeoFlow",
                    "기존 서버 객체와 충돌한 로컬 관로를 수정 작업으로 안전 복구합니다.",
                    level=Qgis.Info,
                    duration=6,
                )
                result = client.post_json(changeset_url, payload)
            acknowledge_outbox(package_path, changeset_id)
            totals["created"] += int(result.get("created") or 0)
            totals["updated"] += int(result.get("updated") or 0)
            totals["deleted"] += int(result.get("deleted") or 0)
            totals["total"] += int(result.get("total") or 0)

        received = self._pull_and_apply_delta(client)
        if pending_count(package_path) == 0 and outbox_count(package_path) == 0:
            self._refresh_local_baseline(
                package_path,
                context.get("manifest") or {},
            )
        return {"ok": True, **totals, "delta_received": received}

    def _sync_active_project(self, client, automatic: bool = False) -> dict:
        context = self.active_context or {}
        if not context.get("sync_supported"):
            raise RuntimeError("현재 프로젝트는 GeoFlow 서버 동기화가 활성화되어 있지 않습니다.")
        package_path = str(context.get("package_path") or "")
        if not package_path:
            raise RuntimeError("GeoFlow 동기화 컨텍스트가 불완전합니다.")
        if self._sync_in_progress:
            return {"ok": True, "created": 0, "updated": 0, "deleted": 0, "total": 0}

        self._sync_in_progress = True
        self._suppress_auto_sync = True
        try:
            if not automatic:
                self._suppress_auto_sync = False
                self._commit_active_edits()
                self._suppress_auto_sync = True
            if context.get("changeset_supported"):
                result = self._sync_changesets(client)
            else:
                sync_url = str(context.get("sync_url") or "")
                if not sync_url:
                    raise RuntimeError("GeoFlow fallback sync URL이 없습니다.")
                result = client.post_file_json(sync_url, package_path, field_name="package")
                self._refresh_local_baseline(package_path, context.get("manifest") or {})
        finally:
            self._suppress_auto_sync = False
            self._sync_in_progress = False

        created = int(result.get("created") or 0)
        updated = int(result.get("updated") or 0)
        deleted = int(result.get("deleted") or 0)
        received = int(result.get("delta_received") or 0)
        if created or updated or deleted or received:
            prefix = "자동 동기화 완료" if automatic else "동기화 완료"
            text = f"{prefix} · 신규 {created} · 수정 {updated} · 삭제 {deleted}"
            if received:
                text += f" · 수신 {received}"
            self.iface.messageBar().pushMessage(
                "GeoFlow",
                text,
                level=Qgis.Success,
                duration=6,
            )
        return result
