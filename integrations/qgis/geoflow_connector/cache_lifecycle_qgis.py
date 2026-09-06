from __future__ import annotations

import os

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import QAction
from qgis.core import Qgis

from .cache_lifecycle import (
    execute_cache_cleanup,
    inventory_cache,
    plan_cache_cleanup,
)


_ACTIVE_UNUSED_DAYS_KEY = "GeoFlowConnector/cache/active_unused_days"
_COMPLETED_GRACE_DAYS_KEY = "GeoFlowConnector/cache/completed_grace_days"
_QUOTA_MB_KEY = "GeoFlowConnector/cache/quota_mb"
_PINNED_PROJECTS_KEY = "GeoFlowConnector/cache/pinned_projects"


def _int_setting(settings: QSettings, key: str, default: int, minimum: int = 0) -> int:
    try:
        value = int(settings.value(key, default))
    except (TypeError, ValueError):
        value = int(default)
    return max(int(minimum), value)


def _pinned_projects(settings: QSettings) -> set[str]:
    value = settings.value(_PINNED_PROJECTS_KEY, [])
    if value in (None, ""):
        return set()
    if isinstance(value, str):
        rows = [value]
    else:
        try:
            rows = list(value)
        except TypeError:
            rows = [value]
    return {str(row) for row in rows if str(row)}


def _write_pinned_projects(settings: QSettings, project_ids: set[str]) -> None:
    settings.setValue(_PINNED_PROJECTS_KEY, sorted(project_ids))


class CacheLifecycleMixin:
    """Apply the approved local QGIS Snapshot retention policy.

    Defaults:
    - active/non-terminal caches: eligible after 90 unused days;
    - completed caches: eligible after a 30 day grace period;
    - dirty/outbox caches: never automatic deletion;
    - pinned projects: never automatic deletion;
    - cache quota: supported but disabled by default until configured.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._cache_pin_action = None

    def initGui(self):
        super().initGui()
        self._cache_pin_action = QAction(
            "현재 GeoFlow 프로젝트 캐시 고정",
            self.iface.mainWindow(),
        )
        self._cache_pin_action.setEnabled(False)
        self._cache_pin_action.triggered.connect(self._toggle_active_cache_pin)
        self.iface.addPluginToMenu("GeoFlow", self._cache_pin_action)

    def unload(self):
        if self._cache_pin_action is not None:
            self.iface.removePluginMenu("GeoFlow", self._cache_pin_action)
            self._cache_pin_action.deleteLater()
            self._cache_pin_action = None
        super().unload()

    def _cache_root(self) -> str:
        return os.path.join(
            self._app_data_location(),
            "GeoFlowConnector",
            "projects",
        )

    def _update_cache_pin_action(self) -> None:
        action = self._cache_pin_action
        if action is None:
            return
        project_id = str((self.active_context or {}).get("project_id") or "")
        if not project_id:
            action.setEnabled(False)
            action.setText("현재 GeoFlow 프로젝트 캐시 고정")
            return
        settings = QSettings()
        pinned = _pinned_projects(settings)
        action.setEnabled(True)
        if project_id in pinned:
            action.setText("현재 GeoFlow 프로젝트 캐시 고정 해제")
        else:
            action.setText("현재 GeoFlow 프로젝트 캐시 고정")

    def _toggle_active_cache_pin(self):
        project_id = str((self.active_context or {}).get("project_id") or "")
        project_code = str((self.active_context or {}).get("project_code") or project_id[:8])
        if not project_id:
            return
        settings = QSettings()
        pinned = _pinned_projects(settings)
        if project_id in pinned:
            pinned.remove(project_id)
            enabled = False
        else:
            pinned.add(project_id)
            enabled = True
        _write_pinned_projects(settings, pinned)
        self._update_cache_pin_action()
        self.iface.messageBar().pushMessage(
            "GeoFlow",
            (
                f"{project_code}: 로컬 Snapshot 자동 정리에서 보호합니다."
                if enabled
                else f"{project_code}: 로컬 Snapshot 고정을 해제했습니다."
            ),
            level=Qgis.Info,
            duration=5,
        )

    def _run_cache_lifecycle(self) -> None:
        root = self._cache_root()
        settings = QSettings()
        active_unused_days = _int_setting(
            settings,
            _ACTIVE_UNUSED_DAYS_KEY,
            90,
            minimum=1,
        )
        completed_grace_days = _int_setting(
            settings,
            _COMPLETED_GRACE_DAYS_KEY,
            30,
            minimum=1,
        )
        quota_mb = _int_setting(settings, _QUOTA_MB_KEY, 0, minimum=0)
        quota_bytes = quota_mb * 1024 * 1024 if quota_mb > 0 else 0
        package_path = str((self.active_context or {}).get("package_path") or "")

        items = inventory_cache(root)
        decisions = plan_cache_cleanup(
            items,
            active_unused_days=active_unused_days,
            completed_grace_days=completed_grace_days,
            quota_bytes=quota_bytes,
            pinned_project_ids=_pinned_projects(settings),
            protected_paths=[package_path] if package_path else [],
        )
        if not decisions:
            return
        result = execute_cache_cleanup(root, decisions)
        if result.deleted_files:
            size_mb = result.deleted_bytes / (1024 * 1024)
            self.iface.messageBar().pushMessage(
                "GeoFlow",
                f"로컬 GIS 캐시 정리 · {result.deleted_files}개 · {size_mb:.1f} MB 확보",
                level=Qgis.Info,
                duration=6,
            )

    def _materialize_project(self, manifest: dict, client, **kwargs) -> dict:
        result = super()._materialize_project(manifest, client, **kwargs)
        self._update_cache_pin_action()
        try:
            self._run_cache_lifecycle()
        except Exception as exc:
            # Cache housekeeping must never block GIS work or synchronization.
            self.iface.messageBar().pushMessage(
                "GeoFlow 로컬 캐시 정리 건너뜀",
                str(exc),
                level=Qgis.Warning,
                duration=6,
            )
        return result
