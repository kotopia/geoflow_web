# 제목: Dynamic Form 객체 바인딩
# 기능: QGIS Feature 값의 로드·변경 추적·로컬 저장을 중앙 저장 계약에 맞게 처리
"""QGIS feature binder for dynamic central forms."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
import json

from qgis.PyQt.QtCore import QDate, QDateTime, Qt
from qgis.core import QgsMessageLog, QgsFeatureRequest, Qgis

from ..common.lifecycle import sole_new_feature
from .boolean_codes import canonical_boolean_code
from .system_defaults import new_feature_defaults


def _clean(value):
    if value is None:
        return None
    try:
        if value.isNull():
            return None
    except AttributeError:
        pass
    return value


def canonical_value(field, value):
    """Normalize widget/QGIS representations before dirty comparison."""
    value = _clean(value)
    kind = str(
        field.get("widget_type") or field.get("semantic_data_type") or "text"
    ).lower()
    value = canonical_boolean_code(field, value)
    if kind in {"combo", "relation"} or field.get("reference_codes") or field.get("worker_reference"):
        return None if value in (None, "") else str(value)
    if kind == "integer":
        if value in (None, ""):
            return 0
        try:
            return int(Decimal(str(value)))
        except (InvalidOperation, TypeError, ValueError):
            return str(value)
    if kind == "decimal":
        if value in (None, ""):
            return Decimal(0)
        try:
            return Decimal(str(value)).normalize()
        except (InvalidOperation, TypeError, ValueError):
            return str(value)
    if kind == "boolean":
        if isinstance(value, str):
            return value.strip().lower() in {"1", "true", "yes", "y", "on"}
        return bool(value)
    if kind == "date":
        if isinstance(value, QDateTime):
            value = value.date()
        if isinstance(value, QDate):
            text = value.toString("yyyy-MM-dd") if value.isValid() else ""
        elif isinstance(value, (dt.datetime, dt.date)):
            text = value.date().isoformat() if isinstance(value, dt.datetime) else value.isoformat()
        else:
            text = str(value or "").strip()[:10]
        return None if not text or text == "1900-01-01" else text
    if kind == "datetime":
        if isinstance(value, QDateTime):
            text = value.toString(Qt.DateFormat.ISODate) if value.isValid() else ""
        elif isinstance(value, dt.datetime):
            text = value.isoformat(timespec="seconds")
        elif isinstance(value, dt.date):
            text = value.isoformat() + "T00:00:00"
        else:
            text = str(value or "").strip().replace(" ", "T")
        if not text or text.startswith("1900-01-01T"):
            return None
        parsed = QDateTime.fromString(text, Qt.DateFormat.ISODate)
        return parsed.toString("yyyy-MM-ddTHH:mm:ss") if parsed.isValid() else text
    if kind in {"text", "multiline", "photo", "hidden"}:
        text = str(value or "").strip()
        return text or None
    return value


# ============================================================
# 중앙 필드와 QGIS Feature 값 연결
# ============================================================
class DynamicFormBinding:
    def __init__(self, page, layer, form, can_write, *, user_context=None,
                 commit_callback=None):
        self.page, self.layer, self.form = page, layer, form
        self.user_context = dict(user_context or {})
        self.commit_callback = commit_callback
        self.can_save = bool(can_write and not layer.readOnly())
        self.feature_id = None
        self.original = {}
        self.source_original = {}
        self.provider_original = None
        self.loading = False
        self.saving = False
        self.dirty = set()
        self.system_default_fields = set()
        self._last_dirty_signature = ()
        form.changed.connect(self.changed)
        form.behaviorChanged.connect(self.behavior_changed)

    def _save_log(self, key, value):
        QgsMessageLog.logMessage(
            f"[SAVE] {key}={value}", "GeoFlow", Qgis.MessageLevel.Info
        )

    def _reset_committed_baseline(self, feature):
        """Reload one authoritative provider snapshot and prove it is clean."""
        self.load(feature, force=True)
        self.dirty.clear()
        self._last_dirty_signature = ()
        self.page.dirty = False
        self._notify_dirty()
        clean = not self.has_actual_changes()
        self._save_log("form_baseline_reset", str(clean).lower())
        return clean

    def dispose(self):
        try:
            self.form.changed.disconnect(self.changed)
        except (RuntimeError, TypeError):
            pass
        try:
            self.form.behaviorChanged.disconnect(self.behavior_changed)
        except (RuntimeError, TypeError):
            pass

    def _feature_values(self, feature):
        extension = {}
        if "ext_data" in feature.fields().names():
            raw = _clean(feature["ext_data"])
            try:
                extension = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except (ValueError, TypeError):
                extension = {}
        extension = extension.get("gis_form", {}) if isinstance(extension, dict) else {}
        values = {}
        names = set(feature.fields().names())
        for field in self.form.fields:
            storage = field["storage"]
            if storage["kind"] == "column" and storage["key"] in names:
                values[field["id"]] = _clean(feature[storage["key"]])
            elif storage["kind"] == "ext_data":
                values[field["id"]] = extension.get(storage["key"])
            else:
                values[field["id"]] = None
        return values

    def _feature_extension(self, feature):
        if "ext_data" not in feature.fields().names():
            return {}
        raw = _clean(feature["ext_data"])
        try:
            value = json.loads(raw) if isinstance(raw, str) else (raw or {})
        except (ValueError, TypeError):
            value = {}
        return dict(value) if isinstance(value, dict) else {}

    def _notify_dirty(self):
        callback = getattr(self.page, "update_dirty", None)
        if callable(callback):
            callback()
        else:
            self.page.dirty = bool(self.dirty)

    def _set_feature_id(self, feature_id):
        """Keep the binding and its page on the same temporary or committed FID."""
        self.feature_id = feature_id
        self.page.feature_id = feature_id

    def _feature_for_id(self, feature_id):
        """Return a valid feature without ever passing None to QGIS."""
        if feature_id is None:
            return None
        try:
            feature = self.layer.getFeature(feature_id)
        except (TypeError, ValueError):
            return None
        return feature if feature.isValid() else None

    def _provider_feature(self, feature_id):
        if feature_id is None: return None
        return next(self.layer.dataProvider().getFeatures(QgsFeatureRequest().setFilterFid(feature_id)), None)

    def _source_matches(self, current):
        if current is None: return False
        provider = self._provider_feature(current.id())
        if self.provider_original is not None:
            if provider is None or self._feature_values(provider) != self.provider_original:
                return False
        elif provider is not None:
            return False
        values = self._feature_values(current)
        buffer = self.layer.editBuffer()
        staged = buffer.changedAttributeValues().get(current.id(), {}) if buffer is not None else {}
        for field in self.form.fields:
            fid=field['id']
            if canonical_value(field, values.get(fid)) == canonical_value(field, self.source_original.get(fid)):
                continue
            storage=field['storage']
            key=storage['key'] if storage['kind']=='column' else 'ext_data' if storage['kind']=='ext_data' else ''
            if self.layer.fields().indexFromName(key) not in staged:
                return False
        return True

    def _resolve_saved_feature(self, saving_feature_id, creating, committed_features):
        """Resolve the provider FID assigned when a temporary new feature commits."""
        if creating:
            valid = [feature for feature in committed_features if feature.isValid()]
            if len(valid) == 1:
                provider_feature = self._feature_for_id(valid[0].id())
                return provider_feature or valid[0]
            selected = self.layer.selectedFeatureIds()
            if len(selected) == 1:
                selected_feature = self._feature_for_id(selected[0])
                if selected_feature is not None:
                    return selected_feature
        return (self._feature_for_id(self.feature_id)
                or self._feature_for_id(getattr(self.page, "feature_id", None))
                or self._feature_for_id(saving_feature_id))

    def load(self, feature, *, force=False):
        if not force and self.has_actual_changes():
            return
        applied_defaults = False
        self.loading = True
        try:
            self._set_feature_id(feature.id())
            self.source_original = self._feature_values(feature)
            provider = self._provider_feature(feature.id())
            self.provider_original = self._feature_values(provider) if provider is not None else None
            self.form.load_values(self.source_original)
            self.original = self.form.values()
            self.system_default_fields.clear()
            if sole_new_feature(self.layer, self.feature_id):
                defaults = new_feature_defaults(
                    self.form.fields, self.source_original, self.user_context
                )
                if defaults:
                    merged = dict(self.source_original)
                    merged.update(defaults)
                    self.form.load_values(merged)
                    self.system_default_fields.update(defaults)
                    # System defaults are the initial state of a new feature,
                    # not user edits. They are still written on first save via
                    # ``system_default_fields`` below.
                    self.original = self.form.values()
                    applied_defaults = True
            self.dirty.clear()
            self._last_dirty_signature = ()
            self.page.dirty = False
            self._notify_dirty()
        finally:
            self.loading = False
        if applied_defaults:
            self.has_actual_changes()

    def clear(self):
        """Return a clean form to its no-feature state without discarding a draft."""
        if self.has_actual_changes():
            return False
        self._reset_empty()
        return True

    def _reset_empty(self):
        self.loading = True
        try:
            self._set_feature_id(None)
            self.original = {}
            self.source_original = {}
            self.form.load_values({})
            self.dirty.clear()
            self._last_dirty_signature = ()
            self.page.dirty = False
            self._notify_dirty()
        finally:
            self.loading = False

    def _edit_buffer_scope(self):
        buffer = self.layer.editBuffer()
        if buffer is None:
            return None, set(), False
        added = set(buffer.addedFeatures())
        affected = (
            added
            | set(buffer.changedAttributeValues())
            | set(buffer.changedGeometries())
            | set(buffer.deletedFeatureIds())
        )
        schema_changed = bool(buffer.addedAttributes() or buffer.deletedAttributeIds())
        return buffer, affected, schema_changed

    def changed(self, field_id):
        if self.loading:
            return
        field = next(row for row in self.form.fields if row["id"] == field_id)
        if not field.get("readonly"):
            self.has_actual_changes()

    def behavior_changed(self):
        if not self.loading:
            self.has_actual_changes()

    def has_actual_changes(self):
        if self.loading or self.feature_id is None:
            return False
        values = self.form.save_values()
        differences = {}
        for field in self.form.fields:
            field_id = field["id"]
            if field.get("readonly") and field_id not in self.system_default_fields:
                continue
            original = self.original.get(field_id)
            current = values.get(field_id)
            if canonical_value(field, original) != canonical_value(field, current):
                differences[field_id] = (original, current)
        for field_id in self.form.save_null_field_ids():
            source = _clean(self.source_original.get(field_id))
            if source is not None:
                differences[field_id] = (source, None)
        self.dirty = set(differences)
        self.page.dirty = bool(self.dirty)
        signature = tuple(
            (field_id, repr(original), repr(current))
            for field_id, (original, current) in sorted(differences.items())
        )
        if signature and signature != self._last_dirty_signature:
            for field_id, (original, current) in differences.items():
                QgsMessageLog.logMessage(
                    f"dynamic_form_dirty field_id={field_id!r} "
                    f"original={original!r} current={current!r}",
                    "GeoFlow",
                    Qgis.MessageLevel.Info,
                )
        self._last_dirty_signature = signature
        self._notify_dirty()
        return self.page.dirty

    def has_form_changes(self):
        self.has_actual_changes()
        return bool(self.dirty)

    def has_pending_feature_edit(self):
        """Return whether the bound feature owns geometry/attribute buffer work."""
        if self.feature_id is None:
            return False
        _buffer, affected, _schema_changed = self._edit_buffer_scope()
        return self.feature_id in affected

    def is_feature_deleted(self):
        """Return whether QGIS has deleted the bound feature in this edit buffer."""
        if self.feature_id is None:
            return False
        buffer = self.layer.editBuffer()
        return bool(
            buffer is not None
            and self.feature_id in set(buffer.deletedFeatureIds() or set())
        )

    def clear_deleted(self):
        """Clear only stale form state; retain QGIS' pending DELETE operation."""
        if not self.is_feature_deleted():
            return False
        self._reset_empty()
        return True

    def clear_after_committed_delete(self, deleted_ids):
        """Detach the form only after the online DELETE and provider commit."""
        if self.feature_id is None or int(self.feature_id) not in {
            int(fid) for fid in (deleted_ids or ())
        }:
            return False
        self._reset_empty()
        return True

    def discard(self):
        """Suppress selection/form callbacks while restoring the current feature."""
        previous_saving,previous_loading=self.saving,self.loading
        self.saving,self.loading=True,True
        try:
            return self._discard_feature()
        finally:
            self.saving,self.loading=previous_saving,previous_loading

    def _discard_feature(self):
        """Restore only this feature; unrelated batch edits remain staged."""
        feature_id = self.feature_id
        if feature_id is None:
            return self.clear()
        buffer, affected, schema_changed = self._edit_buffer_scope()
        added = set(buffer.addedFeatures()) if buffer is not None else set()
        is_new = feature_id in added
        current_touched = feature_id in affected
        unrelated = affected - {feature_id}

        if self.layer.isModified() and current_touched:
            if not unrelated and not schema_changed:
                if not self.layer.rollBack():
                    self.page.note.setText("현재 객체의 QGIS 편집을 취소하지 못했습니다.")
                    return False
                if is_new:
                    self._reset_empty()
                    return True
            elif is_new:
                # Removing an uncommitted added feature is feature-scoped and
                # leaves unrelated edits in this layer untouched.
                if not self.layer.deleteFeature(feature_id):
                    self.page.note.setText("신규 객체의 미저장 편집을 취소하지 못했습니다.")
                    return False
                remaining = self.layer.editBuffer()
                if remaining is not None and feature_id in remaining.addedFeatures():
                    self.page.note.setText("신규 객체가 편집 버퍼에 남아 있어 전환을 중단했습니다.")
                    return False
                self._reset_empty()
                return True
            else:
                provider = self._provider_feature(feature_id)
                if schema_changed or provider is None:
                    self.page.note.setText('필드 구조 변경 또는 원본 객체 부재로 현재 객체만 취소할 수 없습니다.')
                    return False
                changes = dict(buffer.changedAttributeValues().get(feature_id, {}))
                geometry_changed = feature_id in buffer.changedGeometries()
                self.layer.beginEditCommand('GeoFlow 현재 객체 변경 취소')
                ok = True
                for index in changes:
                    if not self.layer.changeAttributeValue(feature_id,index,provider[index]):
                        ok = False; break
                if ok and geometry_changed:
                    ok = self.layer.changeGeometry(feature_id,provider.geometry())
                if not ok:
                    self.layer.destroyEditCommand()
                    self.page.note.setText('현재 객체의 편집 취소에 실패했습니다. 다른 객체의 편집은 유지했습니다.')
                    return False
                self.layer.endEditCommand()

        feature = self._feature_for_id(feature_id)
        if feature is None:
            self._reset_empty()
            return is_new
        self.load(feature, force=True)
        return True

    def save(self):
        self._save_log("start", "true")
        self._save_log(
            "layer",
            str(self.layer.customProperty("geoflow/standard_name", "") or self.layer.name()),
        )
        self._save_log("feature_id", self.feature_id)
        self._save_log("form_dirty_before", str(bool(self.has_actual_changes())).lower())
        self._save_log("qgis_modified_before", str(bool(self.layer.isModified())).lower())
        if not self.can_save or self.feature_id is None:
            self.page.note.setText("현재 권한으로 저장할 수 없습니다.")
            return False
        errors = self.form.validation_errors()
        if errors:
            self.page.note.setText("\n".join(errors))
            return False
        saving_feature_id = self.feature_id
        current = self._feature_for_id(saving_feature_id)
        if not self._source_matches(current):
            self.page.note.setText("객체가 변경되었습니다. 입력을 보존한 뒤 최신 객체를 다시 조회하세요.")
            return False
        self.has_actual_changes()
        values = self.form.save_values()
        creating = self.layer.isModified() and sole_new_feature(self.layer, self.feature_id)
        changed = set(self.dirty)
        if creating:
            changed.update(self.system_default_fields)
        if not changed and not creating and not self.layer.isModified():
            self.page.dirty = False
            self.page.note.setText("변경 없음 · 현재 객체와 입력값이 일치합니다.")
            return True
        if not self.layer.isEditable() and not self.layer.startEditing():
            return False
        names = set(self.layer.fields().names())
        extension = self._feature_extension(current)
        form_data = dict(extension.get("gis_form") or {})
        self.layer.beginEditCommand("GeoFlow 중앙 Dynamic Form")
        ok = True
        for field in self.form.fields:
            if field["id"] not in changed or (
                field.get("readonly") and field["id"] not in self.system_default_fields
            ):
                continue
            storage = field["storage"]
            if storage["kind"] == "column" and storage["key"] in names:
                ok = ok and self.layer.changeAttributeValue(
                    saving_feature_id, self.layer.fields().indexFromName(storage["key"]), values[field["id"]]
                )
            elif storage["kind"] == "ext_data" and "ext_data" in names:
                form_data[storage["key"]] = values[field["id"]]
            else:
                ok = False
        ext_form_changed = any(
            next(row for row in self.form.fields if row["id"] == key)["storage"]["kind"] == "ext_data"
            for key in changed
        )
        if ext_form_changed and "ext_data" in names:
            extension["gis_form"] = form_data
            ok = ok and self.layer.changeAttributeValue(
                saving_feature_id, self.layer.fields().indexFromName("ext_data"),
                json.dumps(extension, ensure_ascii=False, separators=(",", ":")),
            )
        if not ok:
            self.layer.destroyEditCommand()
            self.page.note.setText("중앙 저장 계약과 로컬 필드가 일치하지 않아 입력을 보존했습니다.")
            return False
        self.layer.endEditCommand()
        committed_features = []
        committed_signal = getattr(self.layer, "committedFeaturesAdded", None)
        def capture_committed(_layer_id, features):
            committed_features.extend(features or [])
        if creating and committed_signal is not None:
            committed_signal.connect(capture_committed)
        self.saving = True
        try:
            if callable(self.commit_callback):
                commit_result = self.commit_callback(
                    self.layer, stop_editing=False
                )
                committed = bool(commit_result.get("ok"))
            else:
                commit_result = None
                committed = self.layer.commitChanges(False)
        finally:
            self.saving = False
            if creating and committed_signal is not None:
                try:
                    committed_signal.disconnect(capture_committed)
                except (RuntimeError, TypeError):
                    pass
        self._save_log(
            "changeset_id",
            self.layer.customProperty("geoflow/last_changeset_id", "") or "none",
        )
        self._save_log("server_result", (
            commit_result.get("server_result") if commit_result is not None
            else self.layer.customProperty("geoflow/last_server_result", "not_sent")
        ))
        self._save_log("server_revision", (
            commit_result.get("server_revision") if commit_result is not None
            else self.layer.customProperty("geoflow/last_server_revision", "unknown")
        ) or "unknown")
        self._save_log("provider_commit_called", str(bool(
            commit_result.get("provider_commit_called")
            if commit_result is not None else True
        )).lower())
        self._save_log("provider_commit_result", str(bool(committed)).lower())
        if bool(self.layer.customProperty("geoflow/online_commit_failed", False)):
            self.page.note.setText(
                "GeoFlow 서버 저장 실패 · 변경사항은 QGIS 편집 상태에 남아 있습니다. 다시 저장해 주세요."
            )
            self.has_actual_changes()
            self._save_log("form_dirty_after", str(bool(self.page.dirty)).lower())
            self._save_log("qgis_modified_after", str(bool(self.layer.isModified())).lower())
            return False
        if not committed:
            self.page.note.setText(
                "GeoFlow 서버 저장 실패 · 변경사항은 QGIS 편집 상태에 남아 있습니다. 다시 저장해 주세요."
            )
            self.has_actual_changes()
            self._save_log("form_dirty_after", str(bool(self.page.dirty)).lower())
            self._save_log("qgis_modified_after", str(bool(self.layer.isModified())).lower())
            return False
        self.page.dirty = False
        self.dirty.clear()
        saved_feature = self._resolve_saved_feature(
            saving_feature_id, creating, committed_features
        )
        if saved_feature is None:
            self._set_feature_id(None)
            QgsMessageLog.logMessage(
                "dynamic_form_save committed but provider feature id was not resolved",
                "GeoFlow",
                Qgis.MessageLevel.Warning,
            )
            self.page.note.setText(
                "로컬 저장은 완료됐지만 저장된 객체를 다시 찾지 못했습니다. 레이어를 새로고침하세요."
            )
            self._save_log("form_baseline_reset", "false")
            self._save_log("form_dirty_after", "false")
            self._save_log("qgis_modified_after", str(bool(self.layer.isModified())).lower())
            return True
        self._set_feature_id(saved_feature.id())
        self._reset_committed_baseline(saved_feature)
        self._save_log("form_dirty_after", str(bool(self.page.dirty)).lower())
        self._save_log("qgis_modified_after", str(bool(self.layer.isModified())).lower())
        self.page.note.setText("GeoFlow 서버 저장 완료")
        return True
