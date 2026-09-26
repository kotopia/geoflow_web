"""GIS-domain photo section appended below the central QGIS dynamic form."""
import mimetypes
import os

from qgis.PyQt.QtCore import Qt, QUrl
from qgis.PyQt.QtGui import QDesktopServices, QPixmap
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QVBoxLayout, QWidget,
)
from qgis.core import QgsMessageLog, Qgis


def _log(message):
    QgsMessageLog.logMessage("photo_section " + str(message), "GeoFlow", Qgis.MessageLevel.Info)


class PhotoSection(QGroupBox):
    MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp"}

    def __init__(self, plugin, page, layer, parent=None):
        super().__init__("사진", parent)
        self.plugin, self.page, self.layer = plugin, page, layer
        self.policy = None
        self.photos = []
        self.feature_uuid = ""
        self.mode = ""
        self.root = QVBoxLayout(self)
        self.note = QLabel("사진 정책을 확인하는 중입니다.")
        self.note.setWordWrap(True)
        self.root.addWidget(self.note)
        self.mode_row = QWidget(self)
        mode_layout = QHBoxLayout(self.mode_row)
        mode_layout.setContentsMargins(0, 0, 0, 0)
        mode_layout.addWidget(QLabel("촬영방식"))
        self.mode_select = QComboBox(self.mode_row)
        self.mode_select.currentTextChanged.connect(self._mode_changed)
        mode_layout.addWidget(self.mode_select)
        mode_layout.addStretch(1)
        self.root.addWidget(self.mode_row)
        self.cards = QWidget(self)
        self.cards_layout = QVBoxLayout(self.cards)
        self.cards_layout.setContentsMargins(0, 0, 0, 0)
        self.root.addWidget(self.cards)
        self.setVisible(False)
        _log(f"created layer={layer.name()} definition_layer_id={layer.customProperty('geoflow/definition_layer_id', '') or '-'}")

    def _base_path(self):
        project_id = str(((self.plugin.active_context or {}).get("manifest", {}).get("project") or {}).get("id") or "")
        layer_id = str(self.layer.customProperty("geoflow/definition_layer_id", "") or "")
        return f"/gis/projects/{project_id}/api/layers/{layer_id}/features/{self.feature_uuid}/photos/"

    def set_feature(self, feature):
        self.feature_uuid = ""
        try:
            self.feature_uuid = str(feature["id"] or "")
        except Exception:
            pass
        service = getattr(self.plugin, "_photo_policy_service", None)
        layer_id = str(self.layer.customProperty("geoflow/definition_layer_id", "") or "")
        self.policy = service.policy(layer_id) if service and service.state == "ready" else None
        self.setVisible(bool(self.policy and self.feature_uuid))
        modes = list((self.policy or {}).get("modes") or {})
        _log(f"set_feature feature_uuid={self.feature_uuid or '-'} layer_id={layer_id or '-'} "
             f"service={getattr(service, 'state', 'missing')} policy_found={'yes' if self.policy else 'no'} "
             f"modes={','.join(modes) or '-'} visible={'yes' if self.isVisible() else 'no'} "
             f"readonly={'yes' if self.layer.readOnly() else 'no'}")
        if not self.isVisible():
            return
        modes = self.policy.get("modes") or {self.policy.get("capture_mode"): self.policy.get("template")}
        saved = self.page.binding.photo_capture_mode()
        self.mode = saved if saved in modes else str(self.policy.get("capture_mode") or next(iter(modes), ""))
        self.mode_select.blockSignals(True)
        self.mode_select.clear()
        self.mode_select.addItems(list(modes))
        self.mode_select.setCurrentText(self.mode)
        self.mode_select.blockSignals(False)
        self.mode_row.setVisible(len(modes) > 1)
        self.reload()

    def clear(self):
        self.feature_uuid = ""
        self.photos = []
        self.setVisible(False)

    def _mode_changed(self, mode):
        if not mode or mode == self.mode:
            return
        if self.page.binding.has_actual_changes():
            self.note.setText("일반 속성의 미저장 입력을 먼저 저장하거나 되돌린 뒤 촬영방식을 변경하세요.")
            self.mode_select.blockSignals(True)
            self.mode_select.setCurrentText(self.mode)
            self.mode_select.blockSignals(False)
            return
        if not self.page.binding.set_photo_capture_mode(mode):
            self.note.setText("촬영방식 저장 실패 · 다른 QGIS 편집을 먼저 저장하거나 취소하세요.")
            self.mode_select.blockSignals(True)
            self.mode_select.setCurrentText(self.mode)
            self.mode_select.blockSignals(False)
            return
        self.mode = mode
        self.plugin._run_auto_sync()
        self.note.setText("촬영방식을 저장·동기화했습니다. 기존 사진은 보존됩니다.")
        self.render()

    def reload(self):
        try:
            payload = self.plugin.active_client.get_json(self._base_path() + "?download_urls=1")
            self.photos = payload.get("photos") or []
            self.note.setText("")
            self.render()
        except Exception as exc:
            self.note.setText("사진 조회 실패 · " + str(exc))

    def _clear_cards(self):
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def render(self):
        self._clear_cards()
        modes = self.policy.get("modes") or {}
        template = modes.get(self.mode) or self.policy.get("template") or {}
        self.cards_layout.addWidget(QLabel(str(template.get("name") or self.mode)))
        active_slots = {str(slot.get("id")): slot for slot in template.get("slots") or []}
        for slot in active_slots.values():
            self.cards_layout.addWidget(self._slot_card(slot))
        legacy = [p for p in self.photos if p.get("slot_id") and str(p.get("slot_id")) not in active_slots]
        if legacy:
            box = QGroupBox(f"이전 촬영방식 사진 · {len(legacy)}장 보존")
            lay = QVBoxLayout(box)
            for photo in legacy:
                lay.addWidget(self._photo_row(photo))
            self.cards_layout.addWidget(box)
        if self.policy.get("allow_extra_photo"):
            self.cards_layout.addWidget(self._slot_card(None))

    def _slot_card(self, slot):
        slot_id = str((slot or {}).get("id") or "")
        photos = [p for p in self.photos if str(p.get("slot_id") or "") == slot_id]
        minimum, maximum = int((slot or {}).get("min_count") or 0), int((slot or {}).get("max_count") or 100)
        title = str((slot or {}).get("name") or "추가 사진")
        box = QGroupBox(f"{title}  {len(photos)} / {minimum}" + (" ✓" if len(photos) >= minimum else " !"))
        lay = QVBoxLayout(box)
        for photo in photos:
            lay.addWidget(self._photo_row(photo))
        extras = {}
        schema = ((slot or {}).get("extra_schema") or {}).get("fields") or []
        if schema:
            form = QFormLayout()
            for field in schema:
                widget = QCheckBox() if field.get("kind") == "boolean" else QLineEdit()
                extras[field["key"]] = (field, widget)
                form.addRow(str(field.get("label") or field["key"]), widget)
            lay.addLayout(form)
        add = QPushButton("사진 추가")
        add.setEnabled(len(photos) < maximum and not self.layer.readOnly())
        add.clicked.connect(lambda _=False, s=slot, e=extras: self.upload(s, e))
        lay.addWidget(add)
        return box

    def _photo_row(self, photo):
        row = QWidget()
        lay = QHBoxLayout(row)
        lay.setContentsMargins(0, 0, 0, 0)
        preview = QLabel()
        try:
            image = QPixmap()
            image.loadFromData(self.plugin.active_client.get_bytes(str(photo.get("download_url") or "")))
            aspect = getattr(getattr(Qt, "AspectRatioMode", Qt), "KeepAspectRatio")
            smooth = getattr(getattr(Qt, "TransformationMode", Qt), "SmoothTransformation")
            preview.setPixmap(image.scaled(96, 72, aspect, smooth))
        except Exception:
            preview.setText("미리보기 없음")
        lay.addWidget(preview)
        lay.addWidget(QLabel(str(photo.get("original_name") or "사진")))
        view = QPushButton("보기")
        view.clicked.connect(lambda _=False, url=photo.get("download_url"): QDesktopServices.openUrl(QUrl(str(url))))
        delete = QPushButton("삭제")
        delete.setEnabled(not self.layer.readOnly())
        delete.clicked.connect(lambda _=False, p=photo: self.delete_photo(p))
        lay.addWidget(view)
        lay.addWidget(delete)
        return row

    def upload(self, slot, extras):
        path, _ = QFileDialog.getOpenFileName(self, "GIS 사진 선택", "", "Images (*.jpg *.jpeg *.png *.webp)")
        if not path:
            return
        if os.path.getsize(path) > 25 * 1024 * 1024:
            QMessageBox.warning(self, "사진 추가", "사진은 25MB 이하여야 합니다.")
            return
        mime = self.MIME.get(os.path.splitext(path)[1].lower()) or mimetypes.guess_type(path)[0]
        if mime not in self.MIME.values():
            QMessageBox.warning(self, "사진 추가", "JPG, PNG, WebP 사진만 업로드할 수 있습니다.")
            return
        extra_data = {}
        for key, (field, widget) in extras.items():
            value = widget.isChecked() if isinstance(widget, QCheckBox) else widget.text().strip()
            if field.get("required") and value in (None, ""):
                QMessageBox.warning(self, "사진 추가", str(field.get("label")) + " 값을 입력하세요.")
                return
            if field.get("kind") == "integer" and value != "":
                try: value = int(value)
                except ValueError:
                    QMessageBox.warning(self, "사진 추가", str(field.get("label")) + "은 정수여야 합니다.")
                    return
            if field.get("kind") in {"decimal", "number"} and value != "":
                try: value = float(value)
                except ValueError:
                    QMessageBox.warning(self, "사진 추가", str(field.get("label")) + "은 숫자여야 합니다.")
                    return
            extra_data[key] = value
        try:
            client, slot_id = self.plugin.active_client, (slot or {}).get("id")
            signed = client.post_json(self._base_path(), {"action": "presign", "mime_type": mime, "slot_id": slot_id})
            client.put_presigned_file(signed["presigned_url"], path, signed.get("headers") or {})
            client.post_json(self._base_path(), {"action": "finalize", "id": signed["id"],
                "mime_type": mime, "original_name": os.path.basename(path), "slot_id": slot_id,
                "extra_data": extra_data})
            self.reload()
        except Exception as exc:
            QMessageBox.critical(self, "사진 업로드 실패", str(exc))

    def delete_photo(self, photo):
        yes = getattr(getattr(QMessageBox, "StandardButton", QMessageBox), "Yes")
        if QMessageBox.question(self, "사진 삭제", "선택한 사진을 삭제하시겠습니까?") != yes:
            return
        try:
            self.plugin.active_client.delete_json(self._base_path() + str(photo["id"]) + "/")
            self.reload()
        except Exception as exc:
            QMessageBox.critical(self, "사진 삭제 실패", str(exc))
