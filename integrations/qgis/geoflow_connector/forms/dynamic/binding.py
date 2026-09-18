# 제목: Dynamic Form 객체 바인딩
# 기능: QGIS Feature 값의 로드·변경 추적·로컬 저장을 중앙 저장 계약에 맞게 처리
"""QGIS feature binder for dynamic central forms."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation
import json

from qgis.PyQt.QtCore import QDate, QDateTime, Qt
from qgis.core import QgsMessageLog, Qgis

from ..common.lifecycle import sole_new_feature


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
    def __init__(self, page, layer, form, can_write):
        self.page, self.layer, self.form = page, layer, form
        self.can_save = bool(can_write and not layer.readOnly())
        self.feature_id = None
        self.original = {}
        self.source_original = {}
        self.loading = False
        self.dirty = set()
        self._last_dirty_signature = ()
        form.changed.connect(self.changed)

    def dispose(self):
        try:
            self.form.changed.disconnect(self.changed)
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

    def load(self, feature, *, force=False):
        if not force and self.has_actual_changes():
            return
        self.loading = True
        try:
            self.feature_id = feature.id()
            self.source_original = self._feature_values(feature)
            self.form.load_values(self.source_original)
            self.original = self.form.values()
            self.dirty.clear()
            self._last_dirty_signature = ()
            self.page.dirty = False
        finally:
            self.loading = False

    def clear(self):
        """Return a clean form to its no-feature state without discarding a draft."""
        if self.has_actual_changes():
            return False
        self.loading = True
        try:
            self.feature_id = None
            self.original = {}
            self.source_original = {}
            self.form.load_values({})
            self.dirty.clear()
            self._last_dirty_signature = ()
            self.page.dirty = False
            self.page.feature_id = None
        finally:
            self.loading = False
        return True

    def changed(self, field_id):
        if self.loading:
            return
        field = next(row for row in self.form.fields if row["id"] == field_id)
        if not field.get("readonly"):
            self.has_actual_changes()

    def has_actual_changes(self):
        if self.loading or self.feature_id is None:
            return False
        values = self.form.values()
        differences = {}
        for field in self.form.fields:
            field_id = field["id"]
            if field.get("readonly"):
                continue
            original = self.original.get(field_id)
            current = values.get(field_id)
            if canonical_value(field, original) != canonical_value(field, current):
                differences[field_id] = (original, current)
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
        return self.page.dirty

    def save(self):
        if not self.can_save or self.feature_id is None:
            self.page.note.setText("현재 권한으로 저장할 수 없습니다.")
            return False
        errors = self.form.validation_errors()
        if errors:
            self.page.note.setText("\n".join(errors))
            return False
        current = self.layer.getFeature(self.feature_id)
        if not current.isValid() or self._feature_values(current) != self.source_original:
            self.page.note.setText("객체가 변경되었습니다. 입력을 보존한 뒤 최신 객체를 다시 조회하세요.")
            return False
        self.has_actual_changes()
        values = self.form.values()
        changed = set(self.dirty)
        creating = self.layer.isModified() and sole_new_feature(self.layer, self.feature_id)
        if not changed and not creating:
            self.page.dirty = False
            self.page.note.setText("변경 없음 · 현재 객체와 입력값이 일치합니다.")
            return True
        if self.layer.isModified() and not creating:
            self.page.note.setText("QGIS 레이어에 다른 미저장 편집이 있습니다. 먼저 저장하거나 취소하세요.")
            return False
        if not self.layer.isEditable() and not self.layer.startEditing():
            return False
        names = set(self.layer.fields().names())
        extension = {}
        if "ext_data" in names:
            raw = _clean(current["ext_data"])
            try:
                extension = json.loads(raw) if isinstance(raw, str) else (raw or {})
            except (ValueError, TypeError):
                extension = {}
        if not isinstance(extension, dict):
            extension = {}
        form_data = dict(extension.get("gis_form") or {})
        self.layer.beginEditCommand("GeoFlow 중앙 Dynamic Form")
        ok = True
        for field in self.form.fields:
            if field["id"] not in changed or field.get("readonly"):
                continue
            storage = field["storage"]
            if storage["kind"] == "column" and storage["key"] in names:
                ok = ok and self.layer.changeAttributeValue(
                    self.feature_id, self.layer.fields().indexFromName(storage["key"]), values[field["id"]]
                )
            elif storage["kind"] == "ext_data" and "ext_data" in names:
                form_data[storage["key"]] = values[field["id"]]
            else:
                ok = False
        if any(next(row for row in self.form.fields if row["id"] == key)["storage"]["kind"] == "ext_data"
               for key in changed) and "ext_data" in names:
            extension["gis_form"] = form_data
            ok = ok and self.layer.changeAttributeValue(
                self.feature_id, self.layer.fields().indexFromName("ext_data"),
                json.dumps(extension, ensure_ascii=False, separators=(",", ":")),
            )
        if not ok:
            self.layer.destroyEditCommand()
            self.page.note.setText("중앙 저장 계약과 로컬 필드가 일치하지 않아 입력을 보존했습니다.")
            return False
        self.layer.endEditCommand()
        if not self.layer.commitChanges(False):
            self.page.note.setText("로컬 저장 실패 · 폼 입력과 QGIS 편집 버퍼를 보존했습니다.")
            return False
        self.page.dirty = False
        self.dirty.clear()
        self.load(self.layer.getFeature(self.feature_id), force=True)
        self.page.note.setText("로컬 저장 성공 · 서버 전송 결과는 동기화 상태에서 확인하세요.")
        return True
