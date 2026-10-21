"""Feature-scoped GIS photo manager launched from the form header."""
import os
from uuid import uuid4

from qgis.PyQt.QtCore import Qt, QSettings, QSize, pyqtSignal
from qgis.PyQt.QtGui import QPainter, QPixmap
from qgis.PyQt.QtWidgets import (
    QCheckBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QLabel,
    QInputDialog, QLineEdit, QMenu, QMessageBox, QSizePolicy, QToolButton, QVBoxLayout,
    QWidget,
)
from qgis.PyQt.uic import loadUiType
from qgis.core import QgsMessageLog, Qgis

from .photo_icons import feather_icon
from .photo_normalizer import normalize_photo
from .photo_style import apply_photo_style
from .tabler_icons import tabler_icon
from ..photo_selection import (
    next_photo_slot, photo_classification_options, photo_pending_labels, resolve_selection,
    should_show_extra_photo,
)
from .photo_studio import PhotoStudioDialog


FORMS_DIR = os.path.join(os.path.dirname(__file__), "forms")
FORM_CLASS, _ = loadUiType(os.path.join(FORMS_DIR, "photo_tab.ui"))
CARD_FORM_CLASS, CARD_BASE_CLASS = loadUiType(os.path.join(FORMS_DIR, "photo_card.ui"))
SLOT_FORM_CLASS, SLOT_BASE_CLASS = loadUiType(os.path.join(FORMS_DIR, "photo_slot.ui"))

COMMON_PHOTO_POLICY = {
    "allow_extra_photo": True,
    "templates": [{
        "id": "", "name": "기본 사진",
        "variants": [{"id": "", "name": "기본", "slots": []}],
    }],
}


def _log(message):
    QgsMessageLog.logMessage("[PHOTO] " + str(message), "GeoFlow", Qgis.MessageLevel.Info)


class ResponsivePhotoLabel(QLabel):
    clicked = pyqtSignal()
    MAX_PREVIEW_HEIGHT = 360

    def __init__(self, parent=None):
        super().__init__(parent)
        self._source = QPixmap()
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMinimumWidth(0)
        self.setMinimumHeight(120)
        self.setMaximumHeight(self.MAX_PREVIEW_HEIGHT)
        self.setScaledContents(False)
        policy = QSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        policy.setHeightForWidth(True)
        self.setSizePolicy(policy)
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def setSourcePixmap(self, pixmap):
        self._source = pixmap
        self.updateGeometry()
        self.update()

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        if self._source.isNull() or width <= 0:
            return 120
        scale = min(
            float(width) / max(1, self._source.width()),
            float(self.MAX_PREVIEW_HEIGHT) / max(1, self._source.height()),
            1.0,
        )
        return max(120, min(self.MAX_PREVIEW_HEIGHT, round(self._source.height() * scale)))

    def sizeHint(self):
        return QSize(0, self.heightForWidth(max(1, self.width())))

    def minimumSizeHint(self):
        return QSize(0, 0)

    def paintEvent(self, event):
        if self._source.isNull():
            super().paintEvent(event)
            return
        bounds = self.contentsRect()
        if bounds.width() <= 0 or bounds.height() <= 0:
            return
        target = QSize(
            min(bounds.width(), self._source.width()),
            min(bounds.height(), self._source.height()),
        )
        scaled = self._source.scaled(
            target, Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        x = bounds.x() + (bounds.width() - scaled.width()) // 2
        y = bounds.y() + (bounds.height() - scaled.height()) // 2
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform, True)
        painter.drawPixmap(x, y, scaled)
        painter.end()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
        super().mousePressEvent(event)


class PhotoCardWidget(CARD_BASE_CLASS, CARD_FORM_CLASS):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.photoPreview.setMinimumWidth(0)
        self.photoPreview.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred,
        )


class PhotoSlotWidget(SLOT_BASE_CLASS, SLOT_FORM_CLASS):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.setMinimumWidth(0)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)


class PhotoSection(QWidget, FORM_CLASS):
    availabilityChanged = pyqtSignal(bool)
    tabNeededChanged = pyqtSignal(bool)
    dirtyChanged = pyqtSignal(bool)
    MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
            ".webp": "image/webp"}

    def __init__(self, plugin, page, layer, parent=None):
        super().__init__(parent)
        self.setupUi(self)
        self.plugin, self.page, self.layer = plugin, page, layer
        self.policy, self.photos, self.feature_uuid = None, [], ""
        self.template_id, self.variant_id = "", ""
        self.last_slot_id = ""
        self.extra_section_open = False
        self.action_button = None
        self.pending_add = []
        self.pending_replace = {}
        self.pending_edit = {}
        self.pending_delete = set()
        self._server_lookup_deferred = False
        self._committing = False
        self.retry_button = self.retryButton
        self.template_row, self.variant_row = self.templateRow, self.variantRow
        self.template_select, self.variant_select = self.templateCombo, self.variantCombo
        self.cards = self.cardsHost
        self.cards.setMinimumWidth(0)
        self.cards.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        self.cards_layout = self.cardsLayout
        self.retry_button.clicked.connect(self._retry_policy)
        self.template_select.currentIndexChanged.connect(self._template_changed)
        self.variant_select.currentIndexChanged.connect(self._variant_changed)
        apply_photo_style(self)
        self.setVisible(False)
        _log(f"created layer={layer.name()} definition_layer_id={layer.customProperty('geoflow/definition_layer_id', '') or '-'}")

    def _base_path(self):
        project_id = str(((self.plugin.active_context or {}).get("manifest", {}).get("project") or {}).get("id") or "")
        layer_id = str(self.layer.customProperty("geoflow/definition_layer_id", "") or "")
        return f"/gis/projects/{project_id}/api/layers/{layer_id}/features/{self.feature_uuid}/photos/"

    def _can_write(self):
        return bool(getattr(getattr(self.page, "binding", None), "can_save", False))

    def _set_page_note(self, message, level=Qgis.MessageLevel.Info):
        note = getattr(self.page, "note", None)
        if note is not None:
            note.setText(str(message))
        # The compact form no longer reserves a permanent status row.
        # Surface photo feedback through QGIS' transient message bar instead.
        try:
            self.plugin.iface.messageBar().pushMessage(
                "GeoFlow", str(message), level=level, duration=7
            )
        except (AttributeError, RuntimeError, TypeError):
            pass

    def _show_info(self, message):
        self._set_page_note(message)

    def _show_warning(self, message):
        _log("warning " + str(message))
        self._set_page_note(message, Qgis.MessageLevel.Warning)

    def _show_error(self, message):
        _log("error " + str(message))
        self._set_page_note(message, Qgis.MessageLevel.Critical)

    def _set_available(self, available):
        available = bool(available)
        self.setVisible(available)
        self.availabilityChanged.emit(available)

    def _is_managed_layer(self):
        try:
            return bool(
                self.layer.customProperty("geoflow/managed", False)
                and self.layer.customProperty("geoflow/definition_layer_id", "")
            )
        except RuntimeError:
            return False

    def bind_action_button(self, button):
        """Bind the form-header split button to this feature-scoped photo session."""
        self.action_button = button
        button.setIcon(feather_icon("camera"))
        button.clicked.connect(self.quick_capture)
        button.setText("")
        button.setToolButtonStyle(Qt.ToolButtonStyle.ToolButtonIconOnly)
        button.setPopupMode(QToolButton.ToolButtonPopupMode.DelayedPopup)
        self._sync_action_button()

    def tab_needed(self):
        """Return whether the feature-scoped photo tab should be visible."""
        return bool(self.photos or self.pending_add or self.extra_section_open)

    def _sync_tab_needed(self):
        self.tabNeededChanged.emit(self.tab_needed())

    def _select_dynamic_tab(self):
        tabs = getattr(getattr(self.page, "form", None), "tabs", None)
        if tabs is None:
            return False
        index = tabs.indexOf(self)
        if index < 0:
            return False
        tabs.setCurrentIndex(index)
        self.show()
        return True

    def _allow_extra(self):
        return bool((self.policy or {}).get("allow_extra_photo", True))

    def _show_extra_section(self):
        return should_show_extra_photo(
            self._allow_extra(), self.photos, self.pending_add, self.extra_section_open,
        )

    def _sync_action_button(self):
        button = self.action_button
        if button is None:
            return
        ready = bool(self.feature_uuid and self.policy and self._template() and self._variant())
        # Capability visibility is layer-scoped. Feature selection controls
        # enabled state only, so the header layout never collapses or shifts.
        button.setVisible(self._is_managed_layer())
        button.setEnabled(bool(ready and self._can_write()))
        photos = [row for row in self._display_photos() if not row.get("_pending_delete")]
        variant = self._variant() or {}
        required = sum(int(slot.get("min_count") or 0) for slot in variant.get("slots") or [])
        slot_ids = {str(slot.get("id") or "") for slot in variant.get("slots") or []}
        classified = sum(str(row.get("slot_id") or "") in slot_ids for row in photos)
        button.setText("")
        count_text = (
            f"사진 {min(classified, required)} / {required}"
            if required else f"사진 {len(photos)}장"
        )
        self.photoCountLabel.setText(count_text)
        menu = QMenu(button)
        manage = menu.addAction(
            tabler_icon("photo"), "사진 보기/관리"
        )
        manage.setObjectName("photoManageAction")
        manage.triggered.connect(self.open_manager)
        menu.addSeparator()
        current = menu.addAction(
            "현재: " + str((self._template() or {}).get("name") or "사진") + " / "
            + str((self._variant() or {}).get("name") or "기본")
        )
        current.setEnabled(False)
        menu.addSeparator()
        for slot in variant.get("slots") or []:
            action = menu.addAction(str(slot.get("name") or "사진"))
            action.triggered.connect(lambda _=False, s=slot: self._capture_slot(s))
        if self._allow_extra():
            action = menu.addAction(tabler_icon("photo-star"), "추가 사진")
            action.triggered.connect(self._capture_extra)
        choices = menu.addMenu("촬영방식 변경")
        for template in (self.policy or {}).get("templates") or []:
            for variant_row in template.get("variants") or []:
                label = str(template.get("name") or "사진") + " / " + str(variant_row.get("name") or "기본")
                action = choices.addAction(label)
                action.setCheckable(True)
                action.setChecked(str(template.get("id")) == self.template_id and
                                  str(variant_row.get("id")) == self.variant_id)
                action.triggered.connect(
                    lambda _=False, t=str(template.get("id") or ""),
                    v=str(variant_row.get("id") or ""): self.select_capture_mode(t, v)
                )
        button.setMenu(menu)

    def open_manager(self, _checked=False):
        """Open the central photo tab, or the reusable manager dialog."""
        if not self.feature_uuid or not self.policy or not self._is_managed_layer():
            return
        self.extra_section_open = True
        self.render()
        if self._select_dynamic_tab():
            return
        dialog = self.parentWidget()
        if not isinstance(dialog, QDialog):
            return
        self.render()
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()

    def _capture_extra(self, _checked=False):
        """Open the transient extra-photo area before starting file selection."""
        self.extra_section_open = True
        self.render()
        self.upload(None, {})

    def quick_capture(self):
        if not self.feature_uuid or not self.policy or not self._can_write():
            return
        slot = next_photo_slot(self._variant(), self._display_photos(), self.last_slot_id)
        if slot is None and not self._allow_extra():
            self._show_info("현재 촬영방식의 사진 항목이 모두 완료되었습니다.")
            return
        self._capture_slot(slot)

    def _capture_slot(self, slot):
        schema = ((slot or {}).get("extra_schema") or {}).get("fields") or []
        if not schema:
            self.upload(slot, {})
            return
        dialog = QDialog(self)
        dialog.setWindowTitle(str((slot or {}).get("name") or "사진") + " 추가 입력")
        layout = QVBoxLayout(dialog)
        form = QFormLayout()
        extras = {}
        for field in schema:
            widget = QCheckBox(dialog) if field.get("kind") == "boolean" else QLineEdit(dialog)
            extras[field["key"]] = (field, widget)
            form.addRow(str(field.get("label") or field["key"]), widget)
        layout.addLayout(form)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel,
            parent=dialog,
        )
        buttons.accepted.connect(dialog.accept)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            self.upload(slot, extras)

    def select_capture_mode(self, template_id, variant_id):
        template = self._template(template_id)
        variant = self._variant(template, variant_id)
        if not template or not variant:
            return
        self.template_id = str(template["id"])
        self.variant_id = str(variant["id"])
        self.last_slot_id = ""
        self._remember_selection()
        self._fill_selectors()
        self._show_info("촬영방식을 변경했습니다. 저장 대기 사진은 사진 탭에서 재분류할 수 있습니다.")
        self.render()

    def _clear_policy_ui(self):
        self.policy, self.template_id, self.variant_id = None, "", ""
        for combo in (self.template_select, self.variant_select):
            combo.blockSignals(True); combo.clear(); combo.blockSignals(False); combo.setEnabled(False)
        self.template_row.setVisible(False)
        self.variant_row.setVisible(False)
        self.cardsScrollArea.setVisible(False)
        self._clear_cards()
        self._sync_action_button()

    def _selection_prefix(self):
        project_id = str(((self.plugin.active_context or {}).get("manifest", {}).get("project") or {}).get("id") or "")
        layer_id = str(self.layer.customProperty("geoflow/definition_layer_id", "") or "")
        return f"GeoFlowConnector/photoLastSelection/{project_id}/{layer_id}/"

    def _stored_selection(self):
        settings, prefix = QSettings(), self._selection_prefix()
        return str(settings.value(prefix + "template_id", "") or ""), str(settings.value(prefix + "variant_id", "") or "")

    def _remember_selection(self):
        if not self.template_id or not self.variant_id:
            return
        settings, prefix = QSettings(), self._selection_prefix()
        settings.setValue(prefix + "template_id", self.template_id)
        settings.setValue(prefix + "variant_id", self.variant_id)
        settings.setValue(prefix + f"variants/{self.template_id}", self.variant_id)

    def _fill_selectors(self):
        template = self._template()
        self.template_select.blockSignals(True)
        self.template_select.setCurrentIndex(max(0, self.template_select.findData(self.template_id)))
        self.template_select.blockSignals(False)
        self._fill_variants(template, preferred=self.variant_id)

    def _template(self, template_id=None):
        wanted = str(template_id if template_id is not None else self.template_id)
        return next((row for row in (self.policy or {}).get("templates", []) if str(row.get("id")) == wanted), None)

    def _variant(self, template=None, variant_id=None):
        template = template or self._template()
        wanted = str(variant_id if variant_id is not None else self.variant_id)
        return next((row for row in (template or {}).get("variants", []) if str(row.get("id")) == wanted), None)

    def _retry_policy(self):
        service = getattr(self.plugin, "_photo_policy_service", None)
        if service is not None and getattr(service, "state", "") == "error":
            service.refresh()
        elif self.feature_uuid and self.policy:
            self.reload()

    def set_feature(self, feature):
        previous_uuid = self.feature_uuid
        try:
            self.feature_uuid = str(feature["id"] or "")
        except Exception:
            self.feature_uuid = ""
        if self.feature_uuid != previous_uuid:
            self.extra_section_open = False
            # Object-transition guards protect transient unsaved work.  Photo
            # operations are never restored from a persistent local queue.
            self.pending_add.clear()
            self.pending_replace.clear()
            self.pending_edit.clear()
            self.pending_delete.clear()
        self._server_lookup_deferred = self._is_local_only_feature(feature)
        self.refresh_policy()

    def _is_local_only_feature(self, feature):
        """Whether this UUID is still a local create and absent from the server."""
        try:
            feature_id = feature.id()
            buffer = self.layer.editBuffer()
            if buffer is not None and feature_id in set(buffer.addedFeatures() or {}):
                return True
        except (AttributeError, TypeError, ValueError):
            pass
        return False

    def _refresh_server_lookup_state(self):
        binding = getattr(self.page, "binding", None)
        feature_id = getattr(binding, "feature_id", None)
        if feature_id is None:
            return
        try:
            feature = self.layer.getFeature(feature_id)
        except (TypeError, ValueError):
            return
        if feature.isValid():
            self._server_lookup_deferred = self._is_local_only_feature(feature)

    def has_pending_changes(self):
        return bool(
            self.pending_add
            or self.pending_replace or self.pending_edit or self.pending_delete
        )

    def _notify_dirty(self):
        dirty = self.has_pending_changes()
        self.dirtyChanged.emit(dirty)
        callback = getattr(self.page, "update_dirty", None)
        if callable(callback):
            callback()

    def _reset_pending(self):
        self.pending_add.clear()
        self.pending_replace.clear()
        self.pending_edit.clear()
        self.pending_delete.clear()
        self._notify_dirty()

    def discard_pending(self, *, reload=True):
        self._reset_pending()
        if reload and self.feature_uuid and self.policy:
            self.reload()
        else:
            self.render() if self.policy else None

    def _photo_id(self, photo):
        return str(photo.get("id") or "")

    def _view_photo(self, photo):
        """Overlay pending operations without mutating the server snapshot."""
        row = dict(photo)
        photo_id = self._photo_id(row)
        replacement = self.pending_replace.get(photo_id)
        edit = self.pending_edit.get(photo_id)
        if replacement:
            row.update(original_name=replacement["original_name"], edit_data={},
                       edited_object_key=None, edited_mime_type=None)
            row["_local_original_bytes"] = replacement["data"]
            row["_local_display_bytes"] = replacement["data"]
            row["_pending_replace"] = True
        if edit:
            row["edit_data"] = edit["edit_data"]
            row["_local_display_bytes"] = edit["data"]
            row["_pending_edit"] = True
        if photo_id in self.pending_delete:
            row["_pending_delete"] = True
        return row

    def _display_photos(self):
        server = [self._view_photo(row) for row in self.photos]
        local = []
        for operation in self.pending_add:
            row = {
                "id": operation["local_id"], "template_id": operation["template_id"],
                "variant_id": operation["variant_id"], "slot_id": operation["slot_id"],
                "title": operation.get("title", ""), "note": operation.get("note", ""),
                "original_name": operation["original_name"],
                "extra_data": operation["extra_data"], "edit_data": operation.get("edit_data") or {},
                "_local_original_bytes": operation["data"],
                "_local_display_bytes": operation.get("edit_bytes") or operation["data"],
                "_pending_add": True,
                "_pending_failed": operation.get("_queue_state") == "FAILED_RETRYABLE",
            }
            if operation.get("edit_bytes"):
                row["_pending_edit"] = True
            local.append(row)
        return server + local

    def refresh_policy(self):
        """Re-evaluate the latest selected feature after async policy changes."""
        service = getattr(self.plugin, "_photo_policy_service", None)
        layer_id = str(self.layer.customProperty("geoflow/definition_layer_id", "") or "")
        active_project_id = str(((self.plugin.active_context or {}).get("manifest", {}).get("project") or {}).get("id") or "")
        service_project_id = str(getattr(service, "project_id", "") or "")
        state = getattr(service, "state", "missing")
        if service_project_id != active_project_id:
            _log(f"refresh_ignored project_id={active_project_id or '-'} service_project_id={service_project_id or '-'}")
            return

        self.retry_button.setVisible(False)
        if not self.feature_uuid:
            self._clear_policy_ui()
            self._set_available(False)
            return
        if state in {"idle", "loading"}:
            self._clear_policy_ui()
            self._show_info("사진 정책을 불러오는 중입니다.")
            self._set_available(False)
            self._log_refresh(state, layer_id)
            return
        if state == "error":
            self._clear_policy_ui()
            self._show_error("사진 정책을 불러오지 못했습니다.")
            self.retry_button.setVisible(True)
            self._set_available(True)
            self._log_refresh(state, layer_id)
            return
        if state == "unavailable" and self._is_managed_layer():
            self.policy = dict(COMMON_PHOTO_POLICY)
            self._activate_policy(layer_id, state)
            return

        self.policy = service.policy(layer_id) if state == "ready" else None
        if not self.policy and state == "ready" and self._is_managed_layer():
            self.policy = dict(COMMON_PHOTO_POLICY)
        if not self.policy:
            self._clear_policy_ui()
            self._show_info("이 레이어에 적용된 사진 정책이 없습니다.")
            self._set_available(False)
            self._log_refresh(state, layer_id)
            return

        self._activate_policy(layer_id, state)

    def _activate_policy(self, layer_id, state):
        """Activate central policy or the unclassified common GIS fallback."""

        templates = self.policy.get("templates") or []
        if not templates:
            self._clear_policy_ui()
            self._show_warning("이 레이어의 사진 정책에 사용할 수 있는 Template이 없습니다.")
            self._set_available(False)
            self._log_refresh(state, layer_id)
            return
        saved_template, saved_variant = self._stored_selection()
        self.template_id, self.variant_id = resolve_selection(self.policy, saved_template, saved_variant)
        template = self._template()
        self.template_select.blockSignals(True)
        self.template_select.clear()
        for row in templates:
            self.template_select.addItem(str(row.get("name") or "Template"), str(row["id"]))
        self.template_select.setCurrentIndex(max(0, self.template_select.findData(self.template_id)))
        self.template_select.blockSignals(False)
        self.template_select.setEnabled(self._can_write() and len(templates) > 1)
        self.template_row.setVisible(True)
        self.cardsScrollArea.setVisible(True)
        self._fill_variants(template, preferred=self.variant_id)
        self._remember_selection()
        self._log_refresh(state, layer_id, [str(row.get("name") or row.get("id")) for row in templates])
        self._set_available(True)
        if self._server_lookup_deferred:
            self.photos = []
            self.render()
            _log(
                f"server_lookup_deferred feature_id={self.feature_uuid or '-'} "
                f"layer_id={layer_id or '-'} reason=local_create"
            )
            return
        self.reload()

    def _log_refresh(self, state, layer_id, modes=None):
        _log(f"refreshed project_id={getattr(getattr(self.plugin, '_photo_policy_service', None), 'project_id', '') or '-'} "
             f"revision={getattr(getattr(self.plugin, '_photo_policy_service', None), 'revision', '') or '-'} "
             f"feature_id={self.feature_uuid or '-'} layer_id={layer_id or '-'} service={state} "
             f"policy_found={'yes' if self.policy else 'no'} templates={','.join(modes or []) or '-'} "
             f"visible={'yes' if self.isVisible() else 'no'} readonly={'yes' if self.layer.readOnly() else 'no'}")

    def clear(self):
        self.feature_uuid, self.photos = "", []
        self.extra_section_open = False
        self._reset_pending()
        self._clear_policy_ui()
        self.retry_button.setVisible(False)
        self._set_available(False)
        self._sync_action_button()
        self._sync_tab_needed()
        dialog = self.parentWidget()
        if isinstance(dialog, QDialog):
            dialog.hide()

    def _fill_variants(self, template, preferred=""):
        variants = (template or {}).get("variants") or []
        if not variants:
            self.variant_id = ""
            self.variant_select.blockSignals(True)
            self.variant_select.clear()
            self.variant_select.blockSignals(False)
            self.variant_select.setEnabled(False)
            self.variant_row.setVisible(False)
            return
        remembered = str(QSettings().value(
            self._selection_prefix() + f"variants/{str((template or {}).get('id') or '')}", "") or "")
        wanted = str(preferred or remembered)
        variant = next((row for row in variants if str(row.get("id")) == wanted), None) or variants[0]
        self.variant_select.blockSignals(True)
        self.variant_select.clear()
        for row in variants:
            self.variant_select.addItem(str(row.get("name") or "기본"), str(row["id"]))
        self.variant_select.setCurrentIndex(max(0, self.variant_select.findData(str(variant["id"]))))
        self.variant_select.blockSignals(False)
        self.variant_select.setEnabled(self._can_write() and len(variants) > 1)
        self.variant_row.setVisible(len(variants) > 1)
        self.variant_id = str(variant["id"])
        self._sync_action_button()

    def _template_changed(self, _index):
        template_id = str(self.template_select.currentData() or "")
        template = self._template(template_id)
        if not template or template_id == self.template_id:
            return
        self.template_id = template_id
        self._fill_variants(template)
        self._remember_selection()
        self._show_info("사진 업무 선택을 기억했습니다. 기존 사진은 그대로 보존됩니다.")
        self.render()

    def _variant_changed(self, _index):
        variant_id = str(self.variant_select.currentData() or "")
        if not variant_id or variant_id == self.variant_id:
            return
        self.variant_id = variant_id
        self._remember_selection()
        self._show_info("촬영 방식 선택을 기억했습니다. 다음 객체에도 적용됩니다.")
        self.render()

    def reload(self):
        self._refresh_server_lookup_state()
        if self._server_lookup_deferred:
            self.render()
            return
        try:
            payload = self.plugin.active_client.get_json(self._base_path() + "?download_urls=1")
            self.photos = payload.get("photos") or []
            if not self.pending_add and self.photos:
                classified = next((row for row in self.photos
                                   if row.get("template_id") and row.get("variant_id")), None)
                template = self._template(str((classified or {}).get("template_id") or ""))
                variant = self._variant(template, str((classified or {}).get("variant_id") or ""))
                if template and variant:
                    self.template_id, self.variant_id = str(template["id"]), str(variant["id"])
                    self._fill_selectors()
            self.retry_button.setVisible(False)
            self.render()
            _log(
                f"layer={str(self.layer.customProperty('geoflow/standard_name', '') or '').lower()} "
                f"feature_id={self.feature_uuid or '-'} existing_photos={len(self.photos)}"
            )
        except Exception as exc:
            self._show_error("사진 조회 실패 · " + str(exc))
            self.retry_button.setVisible(True)
            self._set_available(True)

    def _clear_cards(self):
        while self.cards_layout.count():
            item = self.cards_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def render(self):
        self._clear_cards()
        template = self._template() or {}
        variant = self._variant(template) or {}
        active_slots = {str(slot.get("id")): slot for slot in variant.get("slots") or []}
        for slot in active_slots.values():
            self.cards_layout.addWidget(self._slot_card(slot))
        display_photos = self._display_photos()
        legacy = [p for p in display_photos if p.get("slot_id") and
                  (str(p.get("template_id") or "") != self.template_id or
                   str(p.get("variant_id") or "") != self.variant_id)]
        if legacy:
            toggle = QToolButton(self.cards)
            toggle.setText(f"다른 Template/Variant 사진 {len(legacy)}장")
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
        if self._show_extra_section():
            self.cards_layout.addWidget(self._slot_card(None))
        self.cards_layout.addStretch(1)
        self._set_available(bool(self.feature_uuid and self.policy and self._is_managed_layer()))
        self._sync_action_button()
        self._sync_tab_needed()

    def _slot_card(self, slot):
        slot_id = str((slot or {}).get("id") or "")
        photos = [p for p in self._display_photos() if str(p.get("slot_id") or "") == slot_id]
        effective = [p for p in photos if not p.get("_pending_delete")]
        maximum = int((slot or {}).get("max_count") or 100)
        title = str((slot or {}).get("name") or "추가 사진")
        box = PhotoSlotWidget(self.cards)
        box.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        box.slotTitleLabel.setText(title)
        for photo in photos:
            box.photoCardsLayout.addWidget(self._photo_card(photo))
        extras = {}
        schema = ((slot or {}).get("extra_schema") or {}).get("fields") or []
        if schema and len(effective) < maximum:
            for field in schema:
                widget = QCheckBox() if field.get("kind") == "boolean" else QLineEdit()
                extras[field["key"]] = (field, widget)
                box.extraFieldsLayout.addRow(str(field.get("label") or field["key"]), widget)
        box.extraFieldsHost.setVisible(bool(schema and len(effective) < maximum))
        can_add = slot is not None or self._allow_extra()
        box.addPhotoButton.setVisible(can_add and len(effective) < maximum)
        box.addPhotoButton.setEnabled(self._can_write())
        box.addPhotoButton.clicked.connect(lambda _=False, s=slot, e=extras: self.upload(s, e))
        return box

    def _photo_card(self, photo):
        card = PhotoCardWidget(self.cards)
        studio, replace, delete = card.editButton, card.replaceButton, card.deleteButton
        for button, icon, tooltip in ((studio, "photo-star", "보기/편집"),
                                      (replace, "folder-open", "사진 변경"),
                                      (delete, "trash", "삭제")):
            button.setIcon(tabler_icon(icon)); button.setToolTip(tooltip); button.setAccessibleName(tooltip)
        studio.clicked.connect(lambda _=False, p=photo: self.open_studio(p))
        replace.clicked.connect(lambda _=False, p=photo: self.replace_photo_dialog(p))
        delete.clicked.connect(lambda _=False, p=photo: self.delete_photo(p))
        replace.setEnabled(self._can_write())
        delete.setEnabled(self._can_write())
        if photo.get("_pending_delete"):
            delete.setIcon(tabler_icon("trash-off"))
            delete.setToolTip("삭제 취소")
            delete.setAccessibleName("삭제 취소")
        if photo.get("_pending_add"):
            classify = card.classifyButton
            classify.setVisible(True)
            classify.setIcon(tabler_icon("category"))
            classify.setToolTip("사진 종류 변경")
            classify.setAccessibleName("사진 종류 변경")
            classify.clicked.connect(lambda _=False, p=photo: self.reclassify_pending(p))
        preview = ResponsivePhotoLabel(card)
        card.previewLayout.addWidget(preview)
        try:
            image = QPixmap()
            local = photo.get("_local_display_bytes")
            if local:
                image.loadFromData(local)
            else:
                image.loadFromData(self.plugin.active_client.get_bytes(
                    str(photo.get("display_download_url") or photo.get("download_url") or "")
                ))
            preview.setSourcePixmap(image)
        except Exception:
            preview.setText("미리보기를 불러올 수 없습니다.")
        preview.clicked.connect(lambda p=photo: self.open_studio(p))
        card.originalNameLabel.setText("원본: " + str(photo.get("original_name") or "사진"))
        card.originalNameLabel.setToolTip(str(photo.get("original_name") or ""))
        card.titleLabel.setText(str(photo.get("title") or ""))
        card.titleLabel.setVisible(bool(photo.get("title")))
        card.descriptionLabel.setText(str(photo.get("note") or ""))
        card.descriptionLabel.setVisible(bool(photo.get("note")))
        pending = photo_pending_labels(photo)
        if photo.get("_pending_failed"):
            pending_prefix = "● 동기화 실패 · 재시도 예정 · "
        else:
            pending_prefix = "● 미저장 · "
        card.pendingLabel.setText(pending_prefix + ", ".join(pending))
        card.pendingLabel.setVisible(bool(pending))
        card.setProperty("pending", bool(pending))
        card.setEnabled(not photo.get("_pending_delete") or self._can_write())
        return card

    def reclassify_pending(self, photo):
        """Change only pending classification; retain normalized image bytes."""
        photo_id = self._photo_id(photo)
        operation = next((row for row in self.pending_add if row["local_id"] == photo_id), None)
        if operation is None or operation.get("finalized_id"):
            return
        options = photo_classification_options(self.policy, self._allow_extra())
        labels = [row["label"] for row in options]
        current = next((i for i, row in enumerate(options)
                        if row["template_id"] == str(operation.get("template_id") or "")
                        and row["variant_id"] == str(operation.get("variant_id") or "")
                        and row["slot_id"] == str(operation.get("slot_id") or "")), 0)
        label, accepted = QInputDialog.getItem(
            self, "사진 종류 변경", "저장 전 사진 분류", labels, current, False
        )
        if not accepted:
            return
        selected = options[labels.index(label)]
        operation.update(template_id=selected["template_id"] or None,
                         variant_id=selected["variant_id"] or None,
                         slot_id=selected["slot_id"] or None,
                         signed=None, uploaded=False)
        if selected["slot_id"]:
            self.template_id, self.variant_id = selected["template_id"], selected["variant_id"]
            self.last_slot_id = selected["slot_id"]
            self._remember_selection()
            self._fill_selectors()
        self._show_info("사진 파일은 유지하고 분류만 변경했습니다. 상단 저장 시 반영됩니다.")
        self._notify_dirty()
        self.render()

    def open_studio(self, selected):
        photos = [p for p in self._display_photos() if not p.get("_pending_delete")]
        dialog = PhotoStudioDialog(
            self.plugin.active_client, photos, selected, can_write=self._can_write(),
            save_callback=self._save_edit, replace_callback=self._replace_photo,
            parent=self,
        )
        if not dialog.session_expired:
            dialog.exec()

    def _save_edit(self, photo, output_bytes, mime_type, edit_data):
        photo_id = self._photo_id(photo)
        pending_add = next((row for row in self.pending_add if row["local_id"] == photo_id), None)
        if pending_add is not None:
            pending_add.update(edit_bytes=output_bytes, edit_mime_type=mime_type,
                               edit_data=edit_data, edit_signed=None,
                               edit_uploaded=False)
        else:
            self.pending_edit[photo_id] = {
                "data": output_bytes, "mime_type": mime_type, "edit_data": edit_data,
                "signed": None, "uploaded": False,
            }
        self._show_info("사진 편집이 적용되었습니다. 상단 저장을 눌러 최종 반영하세요.")
        self._notify_dirty(); self.render()

    def replace_photo_dialog(self, photo):
        if QMessageBox.question(self, "사진 변경", "사진을 변경하면 기존 편집본이 초기화됩니다. 계속하시겠습니까?") != QMessageBox.StandardButton.Yes:
            return
        path, _ = QFileDialog.getOpenFileName(self, "GIS 사진 변경", "", "Images (*.jpg *.jpeg *.png *.webp)")
        if path:
            try:
                self._replace_photo(photo, path, normalize_photo(path))
            except Exception as exc:
                QMessageBox.critical(self, "사진 변경 실패", str(exc))

    def _replace_photo(self, photo, path, normalized):
        photo_id = self._photo_id(photo)
        pending_add = next((row for row in self.pending_add if row["local_id"] == photo_id), None)
        if pending_add is not None:
            pending_add.update(
                data=normalized.data, mime_type=normalized.mime_type,
                original_name=os.path.basename(path), captured_at=normalized.captured_at,
                image_metadata=normalized.image_metadata, signed=None, uploaded=False,
                edit_bytes=None, edit_data=None,
            )
        else:
            self.pending_replace[photo_id] = {
                "data": normalized.data, "mime_type": normalized.mime_type,
                "original_name": os.path.basename(path), "captured_at": normalized.captured_at,
                "image_metadata": normalized.image_metadata, "signed": None, "uploaded": False,
            }
            self.pending_edit.pop(photo_id, None)
        self._show_info("사진 변경이 저장 대기 중입니다.")
        self._notify_dirty(); self.render()

    def upload(self, slot, extras):
        title, note = "", ""
        if slot is None:
            title, accepted = QInputDialog.getText(self, "추가 사진", "제목 (선택)")
            if not accepted:
                return
            note, accepted = QInputDialog.getMultiLineText(self, "추가 사진", "설명 (선택)")
            if not accepted:
                return
        path, _ = QFileDialog.getOpenFileName(self, "GIS 사진 선택", "", "Images (*.jpg *.jpeg *.png *.webp)")
        if not path:
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
            normalized = normalize_photo(path)
            slot_id = (slot or {}).get("id")
            self.pending_add.append({
                "local_id": "pending:" + str(uuid4()),
                "template_id": self.template_id if slot else None,
                "variant_id": self.variant_id if slot else None, "slot_id": slot_id,
                "title": str(title).strip()[:200], "note": str(note).strip()[:2000],
                "data": normalized.data, "mime_type": normalized.mime_type,
                "original_name": os.path.basename(path), "extra_data": extra_data,
                "captured_at": normalized.captured_at,
                "image_metadata": normalized.image_metadata,
                "signed": None, "uploaded": False, "edit_bytes": None,
                "edit_data": None,
            })
            if slot is None:
                self.extra_section_open = False
            self._show_info("사진이 저장 대기 중입니다. 상단 저장을 눌러 최종 반영하세요.")
            self.last_slot_id = str(slot_id or "")
            self._notify_dirty(); self.render(); self._select_dynamic_tab()
        except Exception as exc:
            QMessageBox.critical(self, "사진 준비 실패", str(exc))

    def delete_photo(self, photo):
        photo_id = self._photo_id(photo)
        if photo.get("_pending_add"):
            operation = next((row for row in self.pending_add
                              if row["local_id"] == photo_id), None)
            self.pending_add[:] = [row for row in self.pending_add if row["local_id"] != photo_id]
            self._show_info("저장 대기 사진을 취소했습니다.")
        elif photo_id in self.pending_delete:
            self.pending_delete.remove(photo_id)
            self._show_info("사진 삭제 예약을 취소했습니다.")
        else:
            if QMessageBox.question(self, "사진 삭제", "상단 저장 시 이 사진을 삭제합니다. 계속하시겠습니까?") != QMessageBox.StandardButton.Yes:
                return
            self.pending_delete.add(photo_id)
            self._show_info("사진이 삭제 예정입니다. 상단 저장 전에는 서버에서 삭제되지 않습니다.")
        self._notify_dirty(); self.render()

    def _upload_signed(self, operation, presign_payload):
        """Resume a staged S3 upload without creating another key after retry."""
        client = self.plugin.active_client
        if operation.get("signed") is None:
            operation["signed"] = client.post_json(self._base_path(), presign_payload)
        if not operation.get("uploaded"):
            signed = operation["signed"]
            try:
                client.put_presigned_bytes(
                    signed["presigned_url"], operation["data"], signed.get("headers") or {}
                )
            except Exception:
                # A later retry receives a fresh 15-minute URL. The immutable
                # unfinalized key, if the network result was ambiguous, remains
                # eligible for the server's normal orphan cleanup lifecycle.
                operation["signed"] = None
                raise
            operation["uploaded"] = True
        return operation["signed"]

    def _remote_photo_ids(self):
        payload = self.plugin.active_client.get_json(self._base_path())
        return {
            str(row.get("id")) for row in (payload.get("photos") or [])
        }

    def _remote_photo_exists(self, photo_id):
        return str(photo_id) in self._remote_photo_ids()

    def _commit_edit_operation(self, photo_id, operation):
        signed = self._upload_signed(operation, {
            "action": "edit_presign", "photo_id": photo_id,
            "mime_type": operation["mime_type"],
        })
        self.plugin.active_client.post_json(self._base_path(), {
            "action": "edit_finalize", "photo_id": photo_id,
            "edit_id": signed["edit_id"], "mime_type": operation["mime_type"],
            "edit_data": operation["edit_data"],
        })

    def commit_pending(self):
        """Serialize save clicks so one pending item cannot upload twice."""
        if self._committing:
            return {
                "ok": True, "completed": 0, "errors": [],
                "remaining": len(self.pending_add), "in_progress": True,
            }
        self._committing = True
        try:
            return self._commit_pending_impl()
        finally:
            self._committing = False

    def _commit_pending_impl(self):
        """Commit transient photos directly; failures remain in this form session."""
        if not self.has_pending_changes():
            return {"ok": True, "completed": 0, "errors": [], "remaining": 0}
        self._refresh_server_lookup_state()
        if self._server_lookup_deferred:
            self._notify_dirty()
            self.render()
            return {
                "ok": False, "completed": 0,
                "errors": ["시설물을 서버에 먼저 저장한 뒤 사진 저장을 다시 시도하세요."],
                "remaining": len(self.pending_add) + len(self.pending_replace)
                + len(self.pending_edit) + len(self.pending_delete),
                "deferred": True,
            }
        errors = []
        completed = 0

        for operation in list(self.pending_add):
            try:
                photo_id = operation.get("finalized_id")
                if not photo_id:
                    # Confirm that the target UUID is readable before presign
                    # and S3 PUT. A local-only/missing feature therefore cannot
                    # create a storage object without a possible relation.
                    remote_ids = self._remote_photo_ids()
                    signed = self._upload_signed(operation, {
                        "action": "presign", "mime_type": operation["mime_type"],
                        "template_id": operation["template_id"],
                        "variant_id": operation["variant_id"], "slot_id": operation["slot_id"],
                    })
                    if str(signed["id"]) not in remote_ids:
                        self.plugin.active_client.post_json(self._base_path(), {
                            "action": "finalize", "id": signed["id"],
                            "mime_type": operation["mime_type"],
                            "original_name": operation["original_name"],
                            "template_id": operation["template_id"],
                            "variant_id": operation["variant_id"], "slot_id": operation["slot_id"],
                            "title": operation.get("title", ""), "note": operation.get("note", ""),
                            "extra_data": operation["extra_data"],
                            "captured_at": operation["captured_at"],
                            "image_metadata": operation["image_metadata"],
                        })
                    photo_id = operation["finalized_id"] = signed["id"]
                if operation.get("edit_bytes"):
                    edit_operation = {
                        "data": operation["edit_bytes"],
                        "mime_type": operation.get("edit_mime_type") or "image/jpeg",
                        "edit_data": operation["edit_data"],
                        "signed": operation.get("edit_signed"),
                        "uploaded": operation.get("edit_uploaded", False),
                    }
                    try:
                        self._commit_edit_operation(photo_id, edit_operation)
                    finally:
                        operation["edit_signed"] = edit_operation.get("signed")
                        operation["edit_uploaded"] = edit_operation.get("uploaded", False)
                self.pending_add.remove(operation); completed += 1
            except Exception as exc:
                errors.append("사진 추가: " + str(exc))

        for photo_id, operation in list(self.pending_replace.items()):
            if photo_id in self.pending_delete:
                continue
            try:
                signed = self._upload_signed(operation, {
                    "action": "replace_presign", "photo_id": photo_id,
                    "mime_type": operation["mime_type"],
                })
                self.plugin.active_client.post_json(self._base_path(), {
                    "action": "replace_finalize", "photo_id": photo_id,
                    "replace_id": signed["replace_id"], "mime_type": operation["mime_type"],
                    "original_name": operation["original_name"],
                    "captured_at": operation["captured_at"],
                    "image_metadata": operation["image_metadata"],
                })
                del self.pending_replace[photo_id]; completed += 1
            except Exception as exc:
                errors.append("사진 변경: " + str(exc))

        for photo_id, operation in list(self.pending_edit.items()):
            if photo_id in self.pending_delete:
                continue
            try:
                self._commit_edit_operation(photo_id, operation)
                del self.pending_edit[photo_id]; completed += 1
            except Exception as exc:
                errors.append("사진 편집: " + str(exc))

        for photo_id in list(self.pending_delete):
            try:
                self.plugin.active_client.delete_json(self._base_path() + photo_id + "/")
                self.pending_delete.remove(photo_id)
                self.pending_replace.pop(photo_id, None)
                self.pending_edit.pop(photo_id, None)
                completed += 1
            except Exception as exc:
                try:
                    removed = not self._remote_photo_exists(photo_id)
                except Exception:
                    removed = False
                if removed:
                    self.pending_delete.remove(photo_id)
                    self.pending_replace.pop(photo_id, None)
                    self.pending_edit.pop(photo_id, None)
                    completed += 1
                else:
                    errors.append("사진 삭제: " + str(exc))

        self._notify_dirty()
        if not errors:
            self.reload()
        else:
            self.render()
        return {
            "ok": not errors, "completed": completed, "errors": errors,
            "remaining": int(self.has_pending_changes()),
        }
