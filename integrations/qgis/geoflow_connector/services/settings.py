"""Project-scoped GeoFlow user preferences.

Business services use this facade instead of knowing QSettings keys.  Values
are deliberately read on every request so an open form observes a saved
setting without a plugin restart.
"""
from __future__ import annotations

import json
import math

from qgis.PyQt.QtCore import QSettings


class SettingsValidationError(ValueError):
    pass


class GeoFlowSettingsService:
    PREFIX = "GeoFlowConnector/projects"
    LEGACY_DEPTH_RADIUS_KEY = "GeoFlowConnector/depthNearbyRadiusMeters"
    DEFAULT_RADIUS_M = 2.0
    DEFAULT_DEPTH_RADIUS_M = DEFAULT_RADIUS_M
    DEFAULT_MANHOLE_RADIUS_M = DEFAULT_RADIUS_M
    MAX_RADIUS_M = 10000.0

    def __init__(self, plugin=None, settings=None):
        self.plugin = plugin
        self.settings = settings or QSettings()

    def project_id(self, explicit=None):
        if explicit not in (None, ""):
            return str(explicit)
        context = getattr(self.plugin, "active_context", None) or {}
        return str(context.get("project_id") or "unscoped")

    def key(self, name, project_id=None):
        project = self.project_id(project_id).replace("/", "%2F")
        return f"{self.PREFIX}/{project}/{str(name).strip('/')}"

    def _value(self, name, default, project_id=None):
        return self.settings.value(self.key(name, project_id), default)

    def _float(self, name, default, project_id=None):
        try:
            value = float(self._value(name, default, project_id))
        except (TypeError, ValueError):
            return float(default)
        return value if math.isfinite(value) and 0 < value <= self.MAX_RADIUS_M else float(default)

    @staticmethod
    def _bool_value(value, default=True):
        if isinstance(value, bool):
            return value
        if value is None:
            return bool(default)
        return str(value).strip().casefold() not in {"0", "false", "no", "off"}

    def default_nearby_radius_m(self, project_id=None):
        return self._float("nearby/default_radius_m", self.DEFAULT_RADIUS_M, project_id)

    def depth_radius_m(self, project_id=None):
        key = self.key("nearby/depth_radius_m", project_id)
        contains = getattr(self.settings, "contains", None)
        present = contains(key) if callable(contains) else (
            self.settings.value(key, None) is not None
        )
        if present:
            return self._float("nearby/depth_radius_m", self.DEFAULT_DEPTH_RADIUS_M, project_id)
        # Preserve installations that used the former global depth option.
        legacy_present = contains(self.LEGACY_DEPTH_RADIUS_KEY) if callable(contains) else (
            self.settings.value(self.LEGACY_DEPTH_RADIUS_KEY, None) is not None
        )
        if not legacy_present:
            return self.default_nearby_radius_m(project_id)
        legacy = self.settings.value(self.LEGACY_DEPTH_RADIUS_KEY, self.DEFAULT_DEPTH_RADIUS_M)
        try:
            legacy = float(legacy)
        except (TypeError, ValueError):
            legacy = self.DEFAULT_DEPTH_RADIUS_M
        return legacy if math.isfinite(legacy) and 0 < legacy <= self.MAX_RADIUS_M else self.DEFAULT_DEPTH_RADIUS_M

    def manhole_radius_m(self, project_id=None):
        return self._float("nearby/manhole_radius_m", self.DEFAULT_MANHOLE_RADIUS_M, project_id)

    def nearest_first(self, project_id=None):
        return self._bool_value(self._value("nearby/nearest_first", True, project_id))

    def show_nearby_button(self, project_id=None):
        return self._bool_value(self._value("form/show_nearby_button", True, project_id))

    def show_previous_button(self, project_id=None):
        return self._bool_value(self._value("form/show_previous_button", True, project_id))

    def show_field_action_buttons(self, project_id=None):
        return self._bool_value(self._value("form/show_field_action_buttons", True, project_id))

    # Stable service API used by business modules and future central rules.
    get_default_nearby_radius = default_nearby_radius_m
    get_depth_radius = depth_radius_m
    get_manhole_radius = manhole_radius_m
    get_nearest_first = nearest_first

    def get_upper_arc_size(self, project_id=None):
        """Disabled until the geometry unit/rendering contract is defined."""
        return None

    def get_lower_arc_size(self, project_id=None):
        """Disabled until the geometry unit/rendering contract is defined."""
        return None

    @classmethod
    def validate_radius(cls, value):
        try:
            value = float(value)
        except (TypeError, ValueError) as exc:
            raise SettingsValidationError("검색 반경은 숫자여야 합니다.") from exc
        if not math.isfinite(value) or value <= 0 or value > cls.MAX_RADIUS_M:
            raise SettingsValidationError(
                f"검색 반경은 0보다 크고 {cls.MAX_RADIUS_M:g}m 이하여야 합니다."
            )
        return value

    def save_nearby(self, *, default_radius_m, depth_radius_m,
                    manhole_radius_m, nearest_first, project_id=None):
        values = {
            "nearby/default_radius_m": self.validate_radius(default_radius_m),
            "nearby/depth_radius_m": self.validate_radius(depth_radius_m),
            "nearby/manhole_radius_m": self.validate_radius(manhole_radius_m),
            "nearby/nearest_first": bool(nearest_first),
        }
        self._save(values, project_id)

    def save_form(self, *, show_nearby_button, show_previous_button,
                  show_field_action_buttons, project_id=None):
        self._save({
            "form/show_nearby_button": bool(show_nearby_button),
            "form/show_previous_button": bool(show_previous_button),
            "form/show_field_action_buttons": bool(show_field_action_buttons),
        }, project_id)

    def reset_project(self, project_id=None):
        prefix = self.key("", project_id).rstrip("/")
        self.settings.remove(prefix)
        self.settings.sync()
        self._log("reset", project_id=self.project_id(project_id))

    def snapshot(self, project_id=None):
        return {
            "default_radius_m": self.default_nearby_radius_m(project_id),
            "depth_radius_m": self.depth_radius_m(project_id),
            "manhole_radius_m": self.manhole_radius_m(project_id),
            "nearest_first": self.nearest_first(project_id),
            "show_nearby_button": self.show_nearby_button(project_id),
            "show_previous_button": self.show_previous_button(project_id),
            "show_field_action_buttons": self.show_field_action_buttons(project_id),
        }

    def _save(self, values, project_id=None):
        for name, value in values.items():
            self.settings.setValue(self.key(name, project_id), value)
        self.settings.sync()
        project = self.project_id(project_id)
        self._emit(f"[SETTINGS] project_id={project}")
        for name, value in values.items():
            self._emit(f"[SETTINGS] {name.replace('/', '.')}={value}")
        self._emit("[SETTINGS] saved=true")

    def _log(self, action, **values):
        self._emit("[SETTINGS] action=" + action + " " + json.dumps(
            values, ensure_ascii=False, sort_keys=True, default=str
        ))

    def _emit(self, message):
        logger = getattr(self.plugin, "log", None)
        if callable(logger):
            logger(message)
