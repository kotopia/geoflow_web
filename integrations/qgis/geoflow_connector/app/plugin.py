# 제목: app/plugin.py
# 기능: 프로젝트 materialize, 레이어 생성, 변경 수집, 로컬 저장 후 동기화 엔진
from __future__ import annotations

import datetime as dt
import hashlib
import json
import os
import re
import sqlite3
from time import perf_counter
import uuid

from qgis.PyQt.QtCore import QSettings, QStandardPaths
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

from ..sync.online import (
    change_signature, read_last_applied_revision, write_last_applied_revision,
)
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
        self._change_origin = "USER_EDIT"
        self._online_save_trigger = "geoflow_save"
        # Retry identity is transient and exists only while this QGIS process is
        # open.  No feature payload is persisted outside QGIS' edit buffer.
        self._online_attempts: dict[str, dict] = {}

    def initGui(self):
        self.action = QAction("GeoFlow Connector", self.iface.mainWindow())
        self.action.triggered.connect(self.run)
        self.iface.addPluginToMenu("GeoFlow", self.action)
        self.iface.addToolBarIcon(self.action)

    def unload(self):
        self._online_attempts.clear()
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

    def _capture_layer_changes(self, layer_id: str, *args) -> list[dict]:
        if self._suppress_auto_sync or self._change_origin != "USER_EDIT":
            return []
        context = self.active_context or {}
        if not context.get("changeset_supported"):
            return []
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is None:
            return []
        buffer = layer.editBuffer()
        if buffer is None:
            return []

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

        return list(changes.values())

    def _log_delete_payload(self, changeset_id, base_revision, changes):
        """Log the DELETE contract shape without values or sensitive content."""
        log = getattr(self, "log", None)
        if not callable(log):
            return
        revision_names = ("object_revision", "revision", "version")
        for change in changes or ():
            if change.get("action") != "delete":
                continue
            revision_name = next(
                (name for name in revision_names if name in change), None
            )
            fields = {
                "changeset_id": changeset_id,
                "base_revision": base_revision,
                "layer": change.get("layer"),
                "feature_id": change.get("id"),
                "operation": change.get("action"),
                "object_revision_field_present": bool(revision_name),
                "object_revision_value": (
                    change.get(revision_name) if revision_name else None
                ),
                "feature_attributes_keys": sorted(
                    str(name) for name in (change.get("attributes") or {})
                ),
                "properties_present": "properties" in change,
                "geometry_present": "geometry_wkb" in change,
            }
            for name, value in fields.items():
                log(f"[DELETE_PAYLOAD] {name}={value}")

    def _log_delete_conflict(self, exc):
        """Preserve redacted 409 diagnostics supplied by the server."""
        log = getattr(self, "log", None)
        if not callable(log):
            return
        rows = []
        for row in getattr(exc, "conflicts", ()):
            rows.append({
                "layer": row.get("layer"), "feature_id": row.get("id"),
                "reason": row.get("reason"),
                "conflict_type": row.get("conflict_type") or row.get("type"),
                "expected_revision": row.get("expected_revision"),
                "actual_revision": row.get("actual_revision")
                    or row.get("current_revision"),
            })
        fields = {
            "http_status": getattr(exc, "http_status", None),
            "error_code": getattr(exc, "code", None),
            "reason": getattr(exc, "reason", None),
            "message": getattr(exc, "server_message", None) or str(exc),
            "conflict_type": getattr(exc, "conflict_type", None),
            "expected_revision": getattr(exc, "expected_revision", None),
            "actual_revision": getattr(exc, "actual_revision", None),
            "raw_response_keys": getattr(exc, "response_keys", []),
            "conflicts": rows,
        }
        for name, value in fields.items():
            log(f"[DELETE_CONFLICT] {name}={value}")

    @staticmethod
    def _snapshot_edit_buffer(layer) -> dict:
        """Copy transient QGIS edits so QGIS 4.2 can restore a vetoed save."""
        buffer = layer.editBuffer()
        if buffer is None:
            return {"added": [], "attributes": {}, "geometries": {}, "deleted": set()}
        return {
            "added": [QgsFeature(feature) for feature in (buffer.addedFeatures() or {}).values()],
            "attributes": {
                int(fid): dict(values)
                for fid, values in (buffer.changedAttributeValues() or {}).items()
            },
            "geometries": {
                int(fid): QgsGeometry(geometry)
                for fid, geometry in (buffer.changedGeometries() or {}).items()
            },
            "deleted": {int(fid) for fid in (buffer.deletedFeatureIds() or set())},
        }

    def _neutralize_failed_commit(self, layer_id: str, layer, replay: dict) -> None:
        """Keep failed changes out of the provider until after commit returns."""
        attempt = self._online_attempts.setdefault(layer_id, {})
        attempt.update(failed=True, replay=replay, sent=False)
        stack = layer.undoStack()
        guard = 0
        while layer.isModified() and stack.canUndo() and guard < 10000:
            stack.undo()
            guard += 1
        if layer.isModified():
            # Managed feature edits are undoable.  Refuse to disguise an
            # unsupported schema/provider edit as an online-only save.
            self.iface.messageBar().pushMessage(
                "GeoFlow 편집 유지 실패",
                "QGIS 편집 버퍼를 안전하게 보존할 수 없는 변경입니다. 저장을 취소하고 레이어를 다시 여세요.",
                level=Qgis.Critical,
                duration=15,
            )

    @staticmethod
    def _restore_failed_edit_buffer(layer, replay: dict) -> None:
        if not layer.isEditable() and not layer.startEditing():
            return
        layer.beginEditCommand("GeoFlow 서버 저장 실패 복원")
        try:
            added_old_ids = {feature.id() for feature in replay.get("added") or []}
            for feature in replay.get("added") or []:
                layer.addFeature(QgsFeature(feature))
            for fid, values in (replay.get("attributes") or {}).items():
                if fid in added_old_ids:
                    continue
                for field_index, value in values.items():
                    layer.changeAttributeValue(int(fid), int(field_index), value)
            for fid, geometry in (replay.get("geometries") or {}).items():
                if fid not in added_old_ids:
                    layer.changeGeometry(int(fid), QgsGeometry(geometry))
            for fid in replay.get("deleted") or set():
                if fid not in added_old_ids:
                    layer.deleteFeature(int(fid))
        finally:
            layer.endEditCommand()

    def _before_online_commit(self, layer_id: str, *args) -> None:
        """Send the current QGIS buffer before allowing its provider commit."""
        if self._suppress_auto_sync or self._change_origin != "USER_EDIT":
            return
        layer = QgsProject.instance().mapLayer(layer_id)
        if layer is None:
            return
        layer.setCustomProperty("geoflow/last_server_result", "pending")
        replay = self._snapshot_edit_buffer(layer)
        context = self.active_context or {}
        client = self.active_client
        changeset_url = str(context.get("changeset_url") or "")
        client_id = str(context.get("client_id") or "")
        package_path = str(context.get("package_path") or "")
        try:
            changes = self._capture_layer_changes(layer_id)
        except Exception as exc:
            self._neutralize_failed_commit(layer_id, layer, replay)
            self.iface.messageBar().pushMessage(
                "GeoFlow 서버 저장 실패",
                f"변경사항을 수집하지 못했습니다: {exc}\nQGIS 편집 상태는 유지됩니다.",
                level=Qgis.Critical,
                duration=15,
            )
            return
        if not changes:
            self._online_attempts.pop(layer_id, None)
            return
        if client is None or not changeset_url or not client_id or not package_path:
            self._neutralize_failed_commit(layer_id, layer, replay)
            self.iface.messageBar().pushMessage(
                "GeoFlow 서버 저장 실패",
                "온라인 저장 연결이 준비되지 않았습니다. 변경사항은 QGIS 편집 상태에 남아 있습니다.",
                level=Qgis.Critical,
                duration=12,
            )
            return

        signature = change_signature(changes)
        attempt = self._online_attempts.get(layer_id)
        if attempt and attempt.get("signature") == signature and attempt.get("sent"):
            return
        if not attempt or attempt.get("signature") != signature:
            attempt = {
                "signature": signature,
                "changeset_id": str(uuid.uuid4()),
                "sent": False,
            }
            self._online_attempts[layer_id] = attempt
        layer.setCustomProperty("geoflow/last_changeset_id", attempt["changeset_id"])
        attempt["replay"] = replay
        try:
            payload = {
                "client_id": str(uuid.UUID(client_id)),
                "changeset_id": attempt["changeset_id"],
                "base_revision": read_last_applied_revision(package_path),
                "changes": changes,
            }
        except Exception as exc:
            self._neutralize_failed_commit(layer_id, layer, replay)
            self.iface.messageBar().pushMessage(
                "GeoFlow 서버 저장 실패",
                f"온라인 저장 컨텍스트를 확인하지 못했습니다: {exc}\nQGIS 편집 상태는 유지됩니다.",
                level=Qgis.Critical,
                duration=15,
            )
            return
        has_delete = any(change.get("action") == "delete" for change in changes)
        self._log_delete_payload(
            attempt["changeset_id"], payload["base_revision"], changes
        )
        self._sync_in_progress = True
        try:
            result = client.post_json(changeset_url, payload)
        except GeoFlowChangesetConflict as exc:
            if has_delete:
                self._log_delete_conflict(exc)
            layer.setCustomProperty("geoflow/last_server_result", "conflict")
            self._neutralize_failed_commit(layer_id, layer, replay)
            self.iface.messageBar().pushMessage(
                "GeoFlow 서버 충돌",
                "서버 객체가 다른 사용자에 의해 변경되었습니다. 현재 변경은 저장되지 않았으며 QGIS 편집 상태에 남아 있습니다. "
                + str(exc),
                level=Qgis.Critical,
                duration=15,
            )
            return
        except Exception as exc:
            layer.setCustomProperty(
                "geoflow/last_server_result", f"failed:{type(exc).__name__}"
            )
            self._neutralize_failed_commit(layer_id, layer, replay)
            self.iface.messageBar().pushMessage(
                "GeoFlow 서버 저장 실패",
                f"{exc}\n변경사항은 QGIS 편집 상태에 남아 있습니다. 다시 저장해 주세요.",
                level=Qgis.Critical,
                duration=15,
            )
            return
        finally:
            self._sync_in_progress = False
        attempt["sent"] = True
        attempt["result"] = dict(result or {})
        layer.setCustomProperty(
            "geoflow/last_server_result",
            json.dumps(dict(result or {}), ensure_ascii=False, sort_keys=True),
        )
        revision = (
            (result or {}).get("new_revision")
            or (result or {}).get("revision")
            or (result or {}).get("current_revision")
        )
        if revision not in (None, ""):
            try:
                write_last_applied_revision(package_path, int(revision))
            except (OSError, sqlite3.Error, TypeError, ValueError):
                # Server save already succeeded.  A later Delta refresh can
                # advance the local cursor; never turn this into a resend.
                pass

    def commit_layers_online(self, layers, *, stop_editing=False,
                             trigger="geoflow_save"):
        """Send multiple layer buffers in one atomic server changeset."""
        unique = []
        seen = set()
        for layer in layers or ():
            if layer is not None and layer.id() not in seen:
                seen.add(layer.id())
                unique.append(layer)
        log = getattr(self, "log", None)
        def event(name, value):
            if callable(log):
                log(f"[ONLINE_SAVE] {name}={value}")
        changes = []
        for layer in unique:
            changes.extend(self._capture_layer_changes(layer.id()))
        counts = {
            action: sum(1 for row in changes if row.get("action") == action)
            for action in ("create", "update", "delete")
        }
        feature_ids = [str(row.get("id") or "") for row in changes]
        layer_names = [str(layer.customProperty(
            "geoflow/standard_name", ""
        ) or layer.name()) for layer in unique]
        event("trigger", trigger)
        event("layer", layer_names)
        event("layers", layer_names)
        event("creates", counts["create"])
        event("updates", counts["update"])
        event("deletes", counts["delete"])
        event("feature_ids", feature_ids)
        if not changes:
            event("server_result", "no_changes")
            event("provider_commit_called", "false")
            event("provider_commit_result", "false")
            event("buffer_dirty_after", any(layer.isModified() for layer in unique))
            return {
                "ok": not any(layer.isModified() for layer in unique),
                "server_result": "no_changes", "operation_counts": counts,
                "provider_commit_called": False,
                "provider_commit_result": False,
            }
        context = self.active_context or {}
        client = self.active_client
        changeset_url = str(context.get("changeset_url") or "")
        client_id = str(context.get("client_id") or "")
        package_path = str(context.get("package_path") or "")
        if client is None or not changeset_url or not client_id or not package_path:
            event("server_result", "not_ready")
            event("provider_commit_called", "false")
            event("provider_commit_result", "false")
            event("buffer_dirty_after", True)
            return {
                "ok": False, "server_result": "not_ready",
                "provider_commit_called": False,
                "provider_commit_result": False,
            }
        signature = change_signature(changes)
        attempt_key = "batch:" + ",".join(sorted(seen))
        attempt = self._online_attempts.get(attempt_key)
        if not attempt or attempt.get("signature") != signature:
            attempt = {
                "signature": signature, "changeset_id": str(uuid.uuid4()),
                "sent": False,
            }
            self._online_attempts[attempt_key] = attempt
        try:
            base_revision = read_last_applied_revision(package_path)
            payload = {
                "client_id": str(uuid.UUID(client_id)),
                "changeset_id": attempt["changeset_id"],
                "base_revision": base_revision,
                "changes": changes,
            }
        except (OSError, sqlite3.Error, TypeError, ValueError):
            event("server_result", "invalid_context")
            event("provider_commit_called", "false")
            event("provider_commit_result", "false")
            event("buffer_dirty_after", True)
            return {
                "ok": False, "server_result": "invalid_context",
                "provider_commit_called": False,
                "provider_commit_result": False,
            }
        event("base_revision", base_revision)
        event("server_revision_before", base_revision)
        event("changeset_id", attempt["changeset_id"])
        event("object_revisions", "not_in_changeset_v1_contract")
        self._log_delete_payload(
            attempt["changeset_id"], base_revision, changes
        )
        event("layer_revisions", {
            name: base_revision for name in layer_names
        })
        for layer in unique:
            layer.setCustomProperty(
                "geoflow/last_changeset_id", attempt["changeset_id"]
            )
            layer.setCustomProperty("geoflow/last_base_revision", base_revision)
        self._sync_in_progress = True
        server_started = perf_counter()
        try:
            result = client.post_json(changeset_url, payload)
        except GeoFlowChangesetConflict as exc:
            self._online_attempts.pop(attempt_key, None)
            if counts["delete"]:
                self._log_delete_conflict(exc)
            server_revision = (getattr(exc, "payload", None) or {}).get(
                "current_revision"
            )
            event("server_result", "conflict")
            event("server_revision_after", server_revision or "unknown")
            event("server_object_revisions", [
                {
                    "layer": row.get("layer"), "id": row.get("id"),
                    "revision": row.get("object_revision")
                    or row.get("revision") or row.get("version"),
                }
                for row in getattr(exc, "conflicts", ())
            ])
            event("provider_commit_called", "false")
            event("provider_commit_result", "false")
            event("buffer_dirty_after", True)
            for layer in unique:
                layer.setCustomProperty("geoflow/last_server_result", "conflict")
                if server_revision not in (None, ""):
                    layer.setCustomProperty(
                        "geoflow/last_server_revision", server_revision
                    )
            self.iface.messageBar().pushMessage(
                "GeoFlow 서버 충돌",
                "서버의 데이터가 현재 로컬 기준보다 변경되었습니다. "
                "현재 삭제/수정 내용은 QGIS 편집 상태에 남아 있습니다.",
                level=Qgis.Critical, duration=15,
            )
            return {
                "ok": False, "server_result": "conflict",
                "server_revision": server_revision,
                "error_code": getattr(exc, "code", None) or "conflict",
                "server_message": getattr(exc, "server_message", None) or str(exc),
                "provider_commit_called": False,
                "provider_commit_result": False,
            }
        except Exception as exc:
            event("server_result", f"failed:{type(exc).__name__}")
            event("server_revision_after", "unknown")
            event("provider_commit_called", "false")
            event("provider_commit_result", "false")
            event("buffer_dirty_after", True)
            self.iface.messageBar().pushMessage(
                "GeoFlow 서버 저장 실패",
                f"{exc}\nProvider commit은 호출되지 않았고 QGIS 편집 버퍼를 유지했습니다.",
                level=Qgis.Critical, duration=15,
            )
            return {
                "ok": False, "server_result": "failed",
                "error_code": getattr(exc, "code", None),
                "server_message": getattr(exc, "server_message", None) or str(exc),
                "error_type": type(exc).__name__,
                "provider_commit_called": False,
                "provider_commit_result": False,
            }
        finally:
            self._sync_in_progress = False
        server_request_ms = (perf_counter() - server_started) * 1000
        attempt["sent"] = True
        attempt["result"] = dict(result or {})
        revision = (
            (result or {}).get("new_revision")
            or (result or {}).get("revision")
            or (result or {}).get("current_revision")
        )
        if revision not in (None, ""):
            try:
                write_last_applied_revision(package_path, int(revision))
            except (OSError, sqlite3.Error, TypeError, ValueError):
                pass
        event("server_result", "success")
        event("server_revision_after", revision or "unknown")
        event("provider_commit_called", "true")
        provider_results = []
        provider_started = perf_counter()
        self._suppress_auto_sync = True
        try:
            for layer in unique:
                provider_results.append(bool(layer.commitChanges(
                    bool(stop_editing)
                )))
        finally:
            self._suppress_auto_sync = False
        committed = bool(provider_results and all(provider_results))
        provider_commit_ms = (perf_counter() - provider_started) * 1000
        event("provider_commit_result", str(committed).lower())
        event("buffer_dirty_after", any(layer.isModified() for layer in unique))
        if committed:
            self._online_attempts.pop(attempt_key, None)
        return {
            "ok": committed, "server_result": "success",
            "server_revision": revision,
            "changeset_id": attempt["changeset_id"],
            "base_revision": base_revision,
            "operation_counts": counts, "feature_ids": feature_ids,
            "server_request_ms": server_request_ms,
            "provider_commit_ms": provider_commit_ms,
            "provider_commit_called": True,
            "provider_commit_result": committed,
        }

    def commit_layer_online(self, layer, *, stop_editing=False):
        """Send one server changeset, then and only then commit the provider."""
        layer_id = layer.id()
        context = self.active_context or {}
        client = self.active_client
        changeset_url = str(context.get("changeset_url") or "")
        client_id = str(context.get("client_id") or "")
        package_path = str(context.get("package_path") or "")
        try:
            changes = self._capture_layer_changes(layer_id)
        except Exception as exc:
            log = getattr(self, "log", None)
            if callable(log):
                log(f"[SAVE] start=true")
                log(f"[SAVE] layer={layer.name()}")
                log(f"[SAVE] server_result=capture_failed:{type(exc).__name__}")
                log("[SAVE] provider_commit_called=false")
            self.iface.messageBar().pushMessage(
                "GeoFlow 서버 저장 실패",
                f"변경사항을 수집하지 못했습니다: {exc}\n"
                "Provider commit은 호출하지 않았고 QGIS 편집 버퍼를 유지했습니다.",
                level=Qgis.Critical, duration=15,
            )
            return {
                "ok": False, "server_result": "capture_failed",
                "provider_commit_called": False,
                "provider_commit_result": False,
            }
        counts = {
            action: sum(1 for row in changes if row.get("action") == action)
            for action in ("create", "update", "delete")
        }
        feature_ids = [str(row.get("id") or "") for row in changes]
        log = getattr(self, "log", None)
        def event(name, value):
            if callable(log):
                log(f"[SAVE] {name}={value}")
        trigger = str(getattr(
            self, "_online_save_trigger", "geoflow_save"
        ) or "geoflow_save")
        def online_event(name, value):
            if callable(log):
                log(f"[ONLINE_SAVE] {name}={value}")
        has_delete = bool(counts["delete"])
        def delete_event(name, value):
            if has_delete and callable(log):
                log(f"[DELETE] {name}={value}")
        event("start", "true")
        event("layer", str(layer.customProperty(
            "geoflow/standard_name", ""
        ) or layer.name()))
        event("qgis_modified_before", str(bool(layer.isModified())).lower())
        event("feature_ids", feature_ids)
        event("operation_counts", counts)
        online_event("trigger", trigger)
        online_event("layer", str(layer.customProperty(
            "geoflow/standard_name", ""
        ) or layer.name()))
        online_event("creates", counts["create"])
        online_event("updates", counts["update"])
        online_event("deletes", counts["delete"])
        online_event("feature_ids", feature_ids)
        if not changes:
            return {
                "ok": not layer.isModified(), "server_result": "no_changes",
                "provider_commit_called": False, "provider_commit_result": False,
            }
        if client is None or not changeset_url or not client_id or not package_path:
            self.iface.messageBar().pushMessage(
                "GeoFlow 서버 저장 실패",
                "온라인 저장 연결이 준비되지 않았습니다. QGIS 편집 버퍼는 유지됩니다.",
                level=Qgis.Critical, duration=12,
            )
            event("server_result", "not_ready")
            event("provider_commit_called", "false")
            event("provider_commit_result", "false")
            event("qgis_modified_after", str(bool(layer.isModified())).lower())
            delete_event("server_result", "not_ready")
            delete_event("provider_commit_called", "false")
            delete_event("provider_commit_result", "false")
            online_event("server_result", "not_ready")
            online_event("provider_commit_called", "false")
            online_event("provider_commit_result", "false")
            online_event("buffer_dirty_after", str(bool(layer.isModified())).lower())
            return {"ok": False, "server_result": "not_ready",
                    "provider_commit_called": False, "provider_commit_result": False}

        signature = change_signature(changes)
        attempt = self._online_attempts.get(layer_id)
        if not attempt or attempt.get("signature") != signature:
            attempt = {
                "signature": signature,
                "changeset_id": str(uuid.uuid4()),
                "sent": False,
            }
            self._online_attempts[layer_id] = attempt
        try:
            base_revision = read_last_applied_revision(package_path)
            payload = {
                "client_id": str(uuid.UUID(client_id)),
                "changeset_id": attempt["changeset_id"],
                "base_revision": base_revision,
                "changes": changes,
            }
        except (OSError, sqlite3.Error, TypeError, ValueError) as exc:
            event("server_result", f"invalid_context:{type(exc).__name__}")
            event("provider_commit_called", "false")
            event("provider_commit_result", "false")
            event("qgis_modified_after", str(bool(layer.isModified())).lower())
            delete_event("server_result", f"invalid_context:{type(exc).__name__}")
            delete_event("provider_commit_called", "false")
            delete_event("provider_commit_result", "false")
            self.iface.messageBar().pushMessage(
                "GeoFlow 서버 저장 실패",
                f"온라인 저장 컨텍스트를 확인하지 못했습니다: {exc}\n"
                "Provider commit은 호출하지 않았고 QGIS 편집 버퍼를 유지했습니다.",
                level=Qgis.Critical, duration=15,
            )
            return {
                "ok": False, "server_result": "invalid_context",
                "provider_commit_called": False,
                "provider_commit_result": False,
            }
        layer.setCustomProperty("geoflow/last_changeset_id", attempt["changeset_id"])
        layer.setCustomProperty("geoflow/last_base_revision", base_revision)
        event("changeset_id", attempt["changeset_id"])
        event("base_revision", base_revision)
        online_event("base_revision", base_revision)
        online_event("server_revision_before", base_revision)
        online_event("changeset_id", attempt["changeset_id"])
        online_event("object_revisions", "not_in_changeset_v1_contract")
        online_event("project_revision", base_revision)
        online_event("layer_revision", layer.customProperty(
            "geoflow/last_server_revision", base_revision
        ))
        delete_event("changeset_id", attempt["changeset_id"])
        delete_event("base_revision", base_revision)
        self._log_delete_payload(
            attempt["changeset_id"], base_revision, changes
        )
        self._sync_in_progress = True
        try:
            result = client.post_json(changeset_url, payload)
        except GeoFlowChangesetConflict as exc:
            self._online_attempts.pop(layer_id, None)
            if has_delete:
                self._log_delete_conflict(exc)
            layer.setCustomProperty("geoflow/last_server_result", "conflict")
            current_revision = (getattr(exc, "payload", None) or {}).get(
                "current_revision"
            )
            if current_revision not in (None, ""):
                layer.setCustomProperty(
                    "geoflow/last_server_revision", current_revision
                )
            event("server_result", "conflict")
            event("server_revision", current_revision or "unknown")
            event("provider_commit_called", "false")
            event("provider_commit_result", "false")
            event("qgis_modified_after", str(bool(layer.isModified())).lower())
            delete_event("server_result", "conflict")
            delete_event("server_revision", current_revision or "unknown")
            delete_event("provider_commit_called", "false")
            delete_event("provider_commit_result", "false")
            online_event("server_result", "conflict")
            online_event("server_revision_after", current_revision or "unknown")
            online_event("server_object_revisions", [
                {
                    "layer": row.get("layer"), "id": row.get("id"),
                    "revision": row.get("object_revision")
                    or row.get("revision") or row.get("version"),
                }
                for row in getattr(exc, "conflicts", ())
            ])
            online_event("provider_commit_called", "false")
            online_event("provider_commit_result", "false")
            online_event("buffer_dirty_after", str(bool(layer.isModified())).lower())
            self.iface.messageBar().pushMessage(
                "GeoFlow 서버 충돌",
                "서버 객체가 변경되었습니다. Provider commit은 호출되지 않았고 QGIS 편집 버퍼를 유지했습니다. "
                + str(exc),
                level=Qgis.Critical, duration=15,
            )
            return {"ok": False, "server_result": "conflict",
                    "provider_commit_called": False, "provider_commit_result": False}
        except Exception as exc:
            layer.setCustomProperty(
                "geoflow/last_server_result", f"failed:{type(exc).__name__}"
            )
            event("server_result", f"failed:{type(exc).__name__}")
            event("provider_commit_called", "false")
            event("provider_commit_result", "false")
            event("qgis_modified_after", str(bool(layer.isModified())).lower())
            delete_event("server_result", f"failed:{type(exc).__name__}")
            delete_event("provider_commit_called", "false")
            delete_event("provider_commit_result", "false")
            online_event("server_result", f"failed:{type(exc).__name__}")
            online_event("server_revision_after", "unknown")
            online_event("provider_commit_called", "false")
            online_event("provider_commit_result", "false")
            online_event("buffer_dirty_after", str(bool(layer.isModified())).lower())
            self.iface.messageBar().pushMessage(
                "GeoFlow 서버 저장 실패",
                f"{exc}\nProvider commit은 호출되지 않았고 QGIS 편집 버퍼를 유지했습니다.",
                level=Qgis.Critical, duration=15,
            )
            return {"ok": False, "server_result": "failed",
                    "provider_commit_called": False, "provider_commit_result": False}
        finally:
            self._sync_in_progress = False

        attempt["sent"] = True
        attempt["result"] = dict(result or {})
        revision = (
            (result or {}).get("new_revision")
            or (result or {}).get("revision")
            or (result or {}).get("current_revision")
        )
        layer.setCustomProperty(
            "geoflow/last_server_result",
            json.dumps(dict(result or {}), ensure_ascii=False, sort_keys=True),
        )
        if revision not in (None, ""):
            try:
                revision_value = int(revision)
                write_last_applied_revision(package_path, revision_value)
            except (OSError, sqlite3.Error, TypeError, ValueError):
                # The server accepted the changeset. A later delta refresh can
                # repair the local cursor without resending this changeset.
                revision_value = str(revision)
            layer.setCustomProperty("geoflow/last_server_revision", revision_value)
        event("server_result", "success")
        event("server_revision", revision or "unknown")
        event("provider_commit_called", "true")
        delete_event("server_result", "success")
        delete_event("server_revision", revision or "unknown")
        delete_event("provider_commit_called", "true")
        online_event("server_result", "success")
        online_event("server_revision_after", revision or "unknown")
        online_event("provider_commit_called", "true")
        self._suppress_auto_sync = True
        try:
            committed = bool(layer.commitChanges(bool(stop_editing)))
        finally:
            self._suppress_auto_sync = False
        event("provider_commit_result", str(committed).lower())
        event("qgis_modified_after", str(bool(layer.isModified())).lower())
        delete_event("provider_commit_result", str(committed).lower())
        online_event("provider_commit_result", str(committed).lower())
        online_event("buffer_dirty_after", str(bool(layer.isModified())).lower())
        if committed:
            layer.setCustomProperty("geoflow/online_commit_failed", False)
            layer.removeCustomProperty("geoflow/pending_delete_ids")
        return {
            "ok": committed,
            "server_result": "success",
            "server_revision": revision,
            "changeset_id": attempt["changeset_id"],
            "base_revision": base_revision,
            "operation_counts": counts,
            "feature_ids": feature_ids,
            "provider_commit_called": True,
            "provider_commit_result": committed,
        }

    def _after_online_commit(self, layer_id: str, *args) -> None:
        """Clear only transient request identity after QGIS commit succeeds."""
        attempt = self._online_attempts.get(layer_id)
        layer = QgsProject.instance().mapLayer(layer_id)
        if attempt and attempt.get("failed"):
            if layer is not None:
                self._restore_failed_edit_buffer(layer, attempt.get("replay") or {})
                layer.setCustomProperty("geoflow/online_commit_failed", True)
            attempt["failed"] = False
            return
        attempt = self._online_attempts.pop(layer_id, None)
        if not attempt or not attempt.get("sent"):
            return
        if layer is not None:
            layer.setCustomProperty("geoflow/online_commit_failed", False)
        result = attempt.get("result") or {}
        self.iface.messageBar().pushMessage(
            "GeoFlow",
            "서버 저장 완료 · 신규 {0} · 수정 {1} · 삭제 {2}".format(
                int(result.get("created") or 0),
                int(result.get("updated") or 0),
                int(result.get("deleted") or 0),
            ),
            level=Qgis.Success,
            duration=6,
        )

    def _discard_captured_layer_changes(self, layer_id: str, *args) -> None:
        """Discard transient retry identity when QGIS rolls its buffer back."""
        self._online_attempts.pop(layer_id, None)

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
            "profile_photo_attachment_id": str(info.get("profile_photo_attachment_id") or ""),
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


    def _assert_no_draft_edits(self) -> None:
        """A sync command must not silently turn an edit buffer into a save."""
        for layer in self._managed_layers():
            try:
                modified = bool(layer.isModified())
            except Exception:
                continue
            if modified:
                raise RuntimeError(
                    "저장하지 않은 편집이 있습니다. 폼 또는 QGIS 편집 도구에서 "
                    "저장하거나 취소한 뒤 동기화하세요."
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

    def _sync_active_project(self, client, automatic: bool = False) -> dict:
        """Refresh server Delta only; outgoing edits are sent at QGIS commit."""
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
            self._assert_no_draft_edits()
            received = self._pull_and_apply_delta(client)
            self._refresh_local_baseline(package_path, context.get("manifest") or {})
            result = {
                "ok": True, "created": 0, "updated": 0, "deleted": 0,
                "total": 0, "delta_received": received,
            }
        finally:
            self._suppress_auto_sync = False
            self._sync_in_progress = False

        created = int(result.get("created") or 0)
        updated = int(result.get("updated") or 0)
        deleted = int(result.get("deleted") or 0)
        received = int(result.get("delta_received") or 0)
        if created or updated or deleted or received:
            text = f"서버 새로고침 완료 · 신규 {created} · 수정 {updated} · 삭제 {deleted}"
            if received:
                text += f" · 수신 {received}"
            self.iface.messageBar().pushMessage(
                "GeoFlow",
                text,
                level=Qgis.Success,
                duration=6,
            )
        return result
