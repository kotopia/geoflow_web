"""QGIS feature binder for dynamic central forms."""
from __future__ import annotations

import json

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


class DynamicFormBinding:
    def __init__(self, page, layer, form, can_write):
        self.page, self.layer, self.form = page, layer, form
        self.can_save = bool(can_write and not layer.readOnly())
        self.feature_id = None
        self.original = {}
        self.loading = False
        self.dirty = set()
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

    def load(self, feature):
        if self.page.dirty:
            return
        self.loading = True
        try:
            self.feature_id = feature.id()
            self.original = self._feature_values(feature)
            self.form.load_values(self.original)
            self.dirty.clear()
            self.page.dirty = False
        finally:
            self.loading = False

    def changed(self, field_id):
        if self.loading:
            return
        field = next(row for row in self.form.fields if row["id"] == field_id)
        if not field.get("readonly"):
            self.dirty.add(field_id)
            self.page.dirty = True

    def save(self):
        if not self.can_save or self.feature_id is None:
            self.page.note.setText("현재 권한으로 저장할 수 없습니다.")
            return False
        errors = self.form.validation_errors()
        if errors:
            self.page.note.setText("\n".join(errors))
            return False
        current = self.layer.getFeature(self.feature_id)
        if not current.isValid() or self._feature_values(current) != self.original:
            self.page.note.setText("객체가 변경되었습니다. 입력을 보존한 뒤 최신 객체를 다시 조회하세요.")
            return False
        values = self.form.values()
        changed = {field_id for field_id in self.dirty if values.get(field_id) != self.original.get(field_id)}
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
        self.load(self.layer.getFeature(self.feature_id))
        self.page.note.setText("로컬 저장 성공 · 서버 전송 결과는 동기화 상태에서 확인하세요.")
        return True
