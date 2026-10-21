"""Shared round/rectangular field switching for selected GIS layers."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


TARGET_STANDARDS = frozenset({"WTL_MANH_PS", "WTL_VALV_PS"})


@dataclass(frozen=True)
class ShapeSwitchConfig:
    name: str
    label: str
    round_keys: tuple[str, ...]
    rect_keys: tuple[str, ...]
    common_keys: tuple[str, ...] = ()

    @property
    def required_keys(self):
        return self.round_keys + self.rect_keys + self.common_keys


SHAPE_SWITCH_CONFIGS = (
    ShapeSwitchConfig(
        "cover_shape", "맨홀뚜껑", ("sbc_size",), ("sbc_size_h", "sbc_size_v")
    ),
    ShapeSwitchConfig(
        "chamber_shape", "변류시설", ("dpg_std",),
        ("dpg_std_h", "dpg_std_v"), ("dpg_dep",)
    ),
)
# Backward-compatible name for policy tests and local callers.
FAMILIES = SHAPE_SWITCH_CONFIGS


def _has_value(value):
    """Match Dynamic Form's practical empty values without treating text '0' as empty."""
    return value not in (None, "", 0, 0.0)


class ShapeSwitchController:
    """One controller reused by every supported Dynamic Form layer."""

    def __init__(self, layer, form, config, parent=None):
        from qgis.PyQt.QtGui import QIcon
        from qgis.PyQt.QtWidgets import QWidget
        from qgis.PyQt.uic import loadUi

        self.layer = layer
        self.form = form
        self.config = config
        self.standard = str(
            layer.customProperty("geoflow/standard_name", "") or ""
        ).upper()
        self.definition_layer_id = str(
            layer.customProperty("geoflow/definition_layer_id", "") or ""
        )
        self._shape = "round"
        self._cleanup_allowed = True
        self._enabled = False
        self._action_field_id = None
        self._field_ids_by_key = self._index_fields()

        self.host = QWidget(parent or form)
        loadUi(
            str(Path(__file__).resolve().parents[1] / "designer" / "shape_switch.ui"),
            self.host,
        )
        self.host.shapeToggleButton.setIcon(
            QIcon(":/geoflow/tabler/arrows-exchange-2.svg")
        )
        from ..form_actions import configure_field_action_button
        configure_field_action_button(self.host.shapeToggleButton)
        self.host.hide()

        if self.standard not in TARGET_STANDARDS:
            return

        self._enabled = self._has_complete_fields()
        if not self._enabled:
            return

        anchor_field_id = self._ids(self.config.round_keys)[0]
        self._action_field_id = anchor_field_id
        self.form.add_field_action(anchor_field_id, self.host)
        self.form.register_save_behavior(self.prepare_save, self.save_null_field_ids)
        self.host.shapeToggleButton.clicked.connect(self.toggle_shape)
        self.form.valuesLoaded.connect(self.sync_from_values)
        self.form.layoutChanged.connect(self.apply_state)
        self.host.show()
        self.sync_from_values()

    @property
    def enabled(self):
        return self._enabled

    @property
    def shape(self):
        return self._shape

    def _log(self, message):
        from qgis.core import QgsMessageLog, Qgis

        QgsMessageLog.logMessage(
            "shape_switch "
            f"standard={self.standard or '-'} "
            f"definition_layer_id={self.definition_layer_id or '-'} "
            f"switch={self.config.name} {message}",
            "GeoFlow",
            Qgis.MessageLevel.Info,
        )

    def _index_fields(self):
        result = {}
        for field in self.form.fields:
            storage = field.get("storage") or {}
            keys = {str(field.get("id") or "").casefold()}
            if storage.get("kind") in {"column", "ext_data"}:
                keys.add(str(storage.get("key") or "").casefold())
            for key in keys - {""}:
                result.setdefault(key, field["id"])
        return result

    def _has_complete_fields(self):
        required = set(self.config.required_keys)
        present = {key for key in required if key in self._field_ids_by_key}
        if present == required:
            return True
        missing = sorted(required - present)
        if present:
            self._log(f"disabled reason=missing_fields fields={','.join(missing)}")
        return False

    def _ids(self, keys):
        return tuple(self._field_ids_by_key[key] for key in keys)

    def _infer_shape(self, values):
        has_round = any(_has_value(values.get(field_id))
                        for field_id in self._ids(self.config.round_keys))
        has_rect = any(_has_value(values.get(field_id))
                       for field_id in self._ids(self.config.rect_keys))
        if has_round and has_rect:
            self._log("conflict values=round_and_rect")
            return "round", True
        if has_rect:
            return "rect", False
        return "round", False

    def sync_from_values(self):
        if not self.enabled:
            return
        shape, conflict = self._infer_shape(self.form.values())
        self._cleanup_allowed = not conflict
        self.set_shape(shape, explicit=False)

    def set_shape(self, shape, *, explicit):
        if not self.enabled or shape not in {"round", "rect"}:
            return
        self._shape = shape
        if explicit:
            self._cleanup_allowed = True
        self.apply_state()
        if explicit:
            self.form.notify_behavior_changed()

    def toggle_shape(self, _checked=False):
        target = "rect" if self._shape == "round" else "round"
        self.set_shape(target, explicit=True)

    def apply_state(self):
        if not self.enabled:
            return
        round_active = self._shape == "round"
        action_field_id = self._ids(
            self.config.round_keys if round_active else self.config.rect_keys
        )[-1]
        if action_field_id != self._action_field_id:
            # Record the destination before rebuilding. layoutChanged is emitted
            # during the move and may call apply_state re-entrantly.
            self._action_field_id = action_field_id
            self.form.move_field_action(action_field_id, self.host)
        self.host.shapeToggleButton.setToolTip(
            "각형으로 전환" if round_active else "원형으로 전환"
        )
        self.host.shapeToggleButton.setAccessibleDescription(
            "현재 원형" if round_active else "현재 각형"
        )
        for field_id in self._ids(self.config.round_keys):
            self.form.set_field_behavior_active(field_id, round_active)
        for field_id in self._ids(self.config.rect_keys):
            self.form.set_field_behavior_active(field_id, not round_active)
        for field_id in self._ids(self.config.common_keys):
            self.form.set_field_behavior_active(field_id, True)

    def save_null_field_ids(self):
        if not self.enabled or not self._cleanup_allowed:
            return set()
        keys = (self.config.rect_keys if self._shape == "round"
                else self.config.round_keys)
        return set(self._ids(keys))

    def prepare_save(self, values):
        for field_id in self.save_null_field_ids():
            values[field_id] = None
        return values


def create_shape_switches(layer, form, parent=None):
    """Create one independent controller instance for every complete field family."""
    return [
        ShapeSwitchController(layer, form, config, parent or form)
        for config in SHAPE_SWITCH_CONFIGS
    ]
