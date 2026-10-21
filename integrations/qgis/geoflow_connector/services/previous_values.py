"""Project/user/layer scoped cache for explicitly requested previous values."""
from __future__ import annotations

import json

from qgis.PyQt.QtCore import QSettings


_EXCLUDED = {
    "id", "uuid", "geom", "geometry", "project_id", "worker_id", "status",
    "date", "survey_date", "work_date", "created_at", "updated_at",
    "created_by", "updated_by", "revision", "source_id", "source_key",
    "source_name", "survey_id", "survey_source_id", "survey_point_id",
    "mapping_id", "link_status", "ext_data",
}
_EXCLUDED_TOKENS = ("photo", "attachment", "revision")


def _name(field):
    storage = field.get("storage") if isinstance(field.get("storage"), dict) else {}
    return str(
        storage.get("key") or field.get("field_name") or
        field.get("field_identifier") or field.get("id") or ""
    ).strip().casefold()


def copy_candidate(field):
    name = _name(field)
    kind = str(field.get("widget_type") or "").casefold()
    storage = field.get("storage") if isinstance(field.get("storage"), dict) else {}
    if (not name or name in _EXCLUDED or any(token in name for token in _EXCLUDED_TOKENS)):
        return False
    if field.get("readonly") or not field.get("visible", True):
        return False
    if kind in {"hidden", "photo", "relation"}:
        return False
    return storage.get("kind") in {"column", "ext_data"}


class PreviousValueService:
    def __init__(self, plugin, settings=None):
        self.plugin = plugin
        self.settings = settings or QSettings()

    def _key(self, standard):
        context = self.plugin.active_context or {}
        user = getattr(self.plugin, "current_user_context", lambda: {})() or {}
        project_id = str(context.get("project_id") or "")
        user_id = str(user.get("user_id") or user.get("worker_id") or "anonymous")
        return f"GeoFlowConnector/previousValues/{project_id}/{user_id}/{str(standard).upper()}"

    def capture(self, page):
        values = page.form.save_values()
        payload = {
            field["id"]: values.get(field["id"])
            for field in page.form.fields
            if copy_candidate(field) and values.get(field["id"]) is not None
        }
        self.settings.setValue(
            self._key(page.standard),
            json.dumps(payload, ensure_ascii=False, separators=(",", ":"), default=str),
        )
        self.settings.sync()
        return len(payload)

    def available(self, page):
        return bool(self.read(page))

    def read(self, page):
        try:
            value = json.loads(str(self.settings.value(self._key(page.standard), "{}") or "{}"))
        except (TypeError, ValueError):
            return {}
        return value if isinstance(value, dict) else {}

    def apply(self, page):
        cached = self.read(page)
        updates = {}
        for field in page.form.fields:
            field_id = field["id"]
            if field_id in cached and copy_candidate(field):
                updates[field_id] = cached[field_id]
        if updates:
            values = page.form.values()
            values.update(updates)
            # Use the form's normal bulk-load path so conditional behaviors
            # (including shape switching) resynchronise after the copy.
            page.form.load_values(values)
            page.binding.has_actual_changes()
        return list(updates)
