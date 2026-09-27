"""Responsive GIS-photo tab for the central QGIS dynamic form."""
import mimetypes
import os

from qgis.PyQt.QtCore import Qt, pyqtSignal
from qgis.PyQt.QtGui import QPixmap
from qgis.PyQt.QtWidgets import (
    QCheckBox, QComboBox, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout,
    QLabel, QLineEdit, QMessageBox, QPushButton, QSizePolicy, QToolButton,
    QVBoxLayout, QWidget,
)
from qgis.core import QgsMessageLog, Qgis

from .photo_editor import PhotoEditorDialog
from .photo_viewer import PhotoViewerDialog


def _log(message):
    QgsMessageLog.logMessage("photo_section " + str(message), "GeoFlow", Qgis.MessageLevel.Info)


class ResponsivePhotoLabel(QLabel):
    clicked = pyqtSignal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumHeight(120)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def setSourcePixmap(self, pixmap):
        self._source = pixmap
        self._fit()

    def _fit(self):
        if self._source.isNull():
            return
        width = max(120, self.contentsRect().width())
        self.setPixmap(self._source.scaled(
            width, 320, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._fit()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class PhotoSection(QGroupBox):
    availabilityChanged = pyqtSignal(bool)
    MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp"}

    def __init__(self, plugin, page, layer, parent=None):
        super().__init__("사진", parent)
        self.plugin, self.page, self.layer = plugin, page, layer
        self.policy, self.photos, self.feature_uuid, self.mode = None, [], "", ""
        self.root = QVBoxLayout(self)
        self.root.setContentsMargins(10, 10, 10, 10)
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
        self.cards_layout.setSpacing(10)
        self.root.addWidget(self.cards)
        self.root.addStretch(1)
        self.setVisible(False)
        _log(f"created layer={layer.name()} definition_layer_id={layer.customProperty('geoflow/definition_layer_id', '') or '-'}")

    def _base_path(self):
        project_id = str(((self.plugin.active_context or {}).get("manifest", {}).get("project") or {}).get("id") or "")
        layer_id = str(self.layer.customProperty("geoflow/definition_layer_id", "") or "")
        return f"/gis/projects/{project_id}/api/layers/{layer_id}/features/{self.feature_uuid}/photos/"

    def _can_write(self):
        return bool(getattr(getattr(self.page, "binding", None), "can_save", False))

    def _set_available(self, available):
        available = bool(available)
        self.setVisible(available)
        self.availabilityChanged.emit(available)

    def set_feature(self, feature):
        try:
            self.feature_uuid = str(feature["id"] or "")
        except Exception:
            self.feature_uuid = ""
        service = getattr(self.plugin, "_photo_policy_service", None)
        layer_id = str(self.layer.customProperty("geoflow/definition_layer_id", "") or "")
        self.policy = service.policy(layer_id) if service and service.state == "ready" else None
        self._set_available(self.policy and self.feature_uuid)
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
        self.mode_select.setEnabled(self._can_write())
        self.mode_row.setVisible(len(modes) > 1)
        self.reload()

    def clear(self):
        self.feature_uuid, self.photos = "", []
        self._set_available(False)

    def _restore_mode(self):
        self.mode_select.blockSignals(True)
        self.mode_select.setCurrentText(self.mode)
        self.mode_select.blockSignals(False)

    def _save_pending_form(self):
        if not self.page.binding.has_actual_changes():
            return True
        dialog = QMessageBox(self)
        dialog.setWindowTitle("촬영방식 변경")
        dialog.setText("일반 속성에 저장하지 않은 입력이 있습니다.")
        save = dialog.addButton("저장 후 변경", QMessageBox.ButtonRole.AcceptRole)
        dialog.addButton("변경 취소", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        return dialog.clickedButton() is save and self.page.binding.save()

    def _current_mode_photos(self):
        modes = (self.policy or {}).get("modes") or {}
        slots = {str(row.get("id")) for row in (modes.get(self.mode) or {}).get("slots") or []}
        return [p for p in self.photos if str(p.get("slot_id") or "") in slots]

    def _mode_changed(self, mode):
        if not mode or mode == self.mode:
            return
        if not self._save_pending_form():
            self.note.setText("촬영방식 변경을 취소했습니다. 일반 속성 입력은 그대로 보존됩니다.")
            self._restore_mode()
            return
        old_photos = self._current_mode_photos()
        delete_old = False
        if old_photos:
            dialog = QMessageBox(self)
            dialog.setWindowTitle("촬영방식 변경")
            dialog.setText(f"{self.mode} 방식 사진 {len(old_photos)}장이 있습니다.\n기존 사진 보존을 권장합니다.")
            keep = dialog.addButton("기존 사진 보존", QMessageBox.ButtonRole.AcceptRole)
            remove = dialog.addButton("기존 사진 삭제 후 변경", QMessageBox.ButtonRole.DestructiveRole)
            dialog.addButton("취소", QMessageBox.ButtonRole.RejectRole)
            dialog.exec()
            if dialog.clickedButton() is remove:
                yes = QMessageBox.StandardButton.Yes
                if QMessageBox.question(self, "기존 사진 삭제", f"기존 {self.mode} 사진 {len(old_photos)}장을 삭제합니다. 계속하시겠습니까?") != yes:
                    self._restore_mode()
                    return
                delete_old = True
            elif dialog.clickedButton() is not keep:
                self._restore_mode()
                return
        if not self.page.binding.set_photo_capture_mode(mode):
            self.note.setText("촬영방식 저장 실패 · QGIS의 다른 미저장 편집을 먼저 저장하거나 취소하세요.")
            self._restore_mode()
            return
        if delete_old:
            try:
                for photo in old_photos:
                    self.plugin.active_client.delete_json(self._base_path() + str(photo["id"]) + "/")
            except Exception as exc:
                self.note.setText("촬영방식은 변경했지만 기존 사진 삭제에 실패했습니다 · " + str(exc))
                self.reload()
                return
        self.mode = mode
        self.plugin._run_auto_sync()
        self.note.setText("촬영방식을 저장·동기화했습니다." + (" 기존 사진을 삭제했습니다." if delete_old else " 기존 사진은 보존됩니다."))
        self.reload()

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
        title = QLabel(str(template.get("name") or self.mode))
        title.setStyleSheet("font-weight: 600; font-size: 14px;")
        self.cards_layout.addWidget(title)
        active_slots = {str(slot.get("id")): slot for slot in template.get("slots") or []}
        for slot in active_slots.values():
            self.cards_layout.addWidget(self._slot_card(slot))
        legacy = [p for p in self.photos if p.get("slot_id") and str(p.get("slot_id")) not in active_slots]
        if legacy:
            toggle = QToolButton(self.cards)
            toggle.setText(f"이전 촬영방식 사진 {len(legacy)}장")
            toggle.setCheckable(True)
            toggle.setArrowType(Qt.ArrowType.RightArrow)
            legacy_host = QWidget(self.cards)
            legacy_layout = QVBoxLayout(legacy_host)
            legacy_layout.setContentsMargins(10, 0, 0, 0)
            for photo in legacy:
                legacy_layout.addWidget(self._photo_card(photo))
            legacy_host.setVisible(False)
            def toggle_legacy(checked, host=legacy_host, button=toggle):
                host.setVisible(checked)
                button.setArrowType(Qt.ArrowType.DownArrow if checked else Qt.ArrowType.RightArrow)
            toggle.toggled.connect(toggle_legacy)
            self.cards_layout.addWidget(toggle)
            self.cards_layout.addWidget(legacy_host)
        if self.policy.get("allow_extra_photo"):
            self.cards_layout.addWidget(self._slot_card(None))

    def _slot_card(self, slot):
        slot_id = str((slot or {}).get("id") or "")
        photos = [p for p in self.photos if str(p.get("slot_id") or "") == slot_id]
        minimum, maximum = int((slot or {}).get("min_count") or 0), int((slot or {}).get("max_count") or 100)
        title = str((slot or {}).get("name") or "추가 사진")
        box = QGroupBox(f"{title}  {len(photos)} / {minimum}" + (" ✓" if len(photos) >= minimum else " !"))
        box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        lay = QVBoxLayout(box)
        for photo in photos:
            lay.addWidget(self._photo_card(photo))
        extras = {}
        schema = ((slot or {}).get("extra_schema") or {}).get("fields") or []
        if schema and len(photos) < maximum:
            form = QFormLayout()
            for field in schema:
                widget = QCheckBox() if field.get("kind") == "boolean" else QLineEdit()
                extras[field["key"]] = (field, widget)
                form.addRow(str(field.get("label") or field["key"]), widget)
            lay.addLayout(form)
        if len(photos) < maximum:
            add = QPushButton("+ 사진 추가")
            add.setEnabled(self._can_write())
            add.clicked.connect(lambda _=False, s=slot, e=extras: self.upload(s, e))
            lay.addWidget(add, 0, Qt.AlignmentFlag.AlignHCenter)
        return box

    def _photo_card(self, photo):
        card = QGroupBox(self.cards)
        lay = QVBoxLayout(card)
        buttons = QHBoxLayout()
        view, edit, delete = QPushButton("원본보기"), QPushButton("편집"), QPushButton("삭제")
        view.clicked.connect(lambda _=False, p=photo: self.open_viewer(p))
        edit.clicked.connect(lambda _=False, p=photo: self.edit_photo(p))
        delete.clicked.connect(lambda _=False, p=photo: self.delete_photo(p))
        edit.setEnabled(self._can_write())
        delete.setEnabled(self._can_write())
        buttons.addWidget(view)
        buttons.addWidget(edit)
        buttons.addWidget(delete)
        buttons.addStretch(1)
        lay.addLayout(buttons)
        preview = ResponsivePhotoLabel(card)
        try:
            image = QPixmap()
            image.loadFromData(self.plugin.active_client.get_bytes(str(photo.get("display_download_url") or photo.get("download_url") or "")))
            preview.setSourcePixmap(image)
        except Exception:
            preview.setText("미리보기를 불러올 수 없습니다.")
        preview.clicked.connect(lambda p=photo: self.open_viewer(p))
        lay.addWidget(preview)
        original = QLabel("원본: " + str(photo.get("original_name") or "사진"))
        original.setWordWrap(True)
        original.setStyleSheet("color: #6b7280; font-size: 11px;")
        original.setToolTip(str(photo.get("original_name") or ""))
        lay.addWidget(original)
        return card

    def open_viewer(self, selected):
        photos = [p for p in self.photos if p.get("original_download_url") or p.get("download_url")]
        PhotoViewerDialog(self.plugin.active_client, photos, selected, self).exec()

    def edit_photo(self, photo):
        try:
            raw = self.plugin.active_client.get_bytes(str(photo.get("display_download_url") or photo.get("download_url") or ""))
            dialog = PhotoEditorDialog(raw, self)
            accepted = getattr(getattr(dialog, "DialogCode", dialog), "Accepted")
            if dialog.exec() != accepted or not dialog.output_bytes:
                return
            client = self.plugin.active_client
            signed = client.post_json(self._base_path(), {"action": "edit_presign", "photo_id": photo["id"], "mime_type": "image/png"})
            client.put_presigned_bytes(signed["presigned_url"], dialog.output_bytes, signed.get("headers") or {})
            client.post_json(self._base_path(), {"action": "edit_finalize", "photo_id": photo["id"],
                "edit_id": signed["edit_id"], "mime_type": "image/png", "edit_data": dialog.edit_data})
            self.reload()
        except Exception as exc:
            QMessageBox.critical(self, "사진 편집 저장 실패", str(exc))

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
                try:
                    value = int(value)
                except ValueError:
                    QMessageBox.warning(self, "사진 추가", str(field.get("label")) + "은 정수여야 합니다.")
                    return
            if field.get("kind") in {"decimal", "number"} and value != "":
                try:
                    value = float(value)
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
        if QMessageBox.question(self, "사진 삭제", "이 사진을 삭제하시겠습니까?") != QMessageBox.StandardButton.Yes:
            return
        try:
            self.plugin.active_client.delete_json(self._base_path() + str(photo["id"]) + "/")
            self.reload()
        except Exception as exc:
            QMessageBox.critical(self, "사진 삭제 실패", str(exc))
