# 제목: cache/reuse.py
# 기능: 프로젝트 열기 시 검증된 로컬 snapshot 재사용 연결
from __future__ import annotations

import datetime as dt
import os

from qgis.PyQt.QtCore import QSettings
from qgis.PyQt.QtWidgets import QMessageBox
from qgis.core import QgsProject, QgsRectangle, QgsVectorLayer, Qgis

from ..layers.default_style import apply_default_qgis_style
from ..sync.online import clear_legacy_queue, legacy_queue_packages
from .snapshot import select_reusable_snapshot, stamp_snapshot


_SNAPSHOT_REQUIRED_TEXT = "서버 Delta 보존 범위를 벗어났습니다."


# ============================================================
# 검증된 프로젝트 Snapshot 재사용
# ============================================================
class SnapshotReuseMixin:
    """Open a valid local project Snapshot and catch up with Delta only.

    The first open still downloads a server GeoPackage. Later opens validate the
    cached package against the current project/definition-revision/layer schema and reuse it
    in place. Legacy queue rows are inert and handled only by an explicit
    one-time migration prompt.
    """

    def _pull_clean_snapshot_delta(self, client, package_path: str, manifest: dict) -> int:
        """Apply server Delta and make the local recovery baseline match it.

        A clean reusable Snapshot has no local work to preserve.  Delta rows
        applied here are server state, not user edits; leaving the old baseline
        behind makes the next open queue those rows as local changes.
        """
        self.log('project_materialize_delta_pull_start')
        received = self._pull_and_apply_delta(client)
        self._refresh_local_baseline(package_path, manifest)
        self.log(f'project_materialize_delta_pull_done count={received}')
        return received

    def _materialize_project(
        self,
        manifest: dict,
        client,
        *,
        _force_snapshot: bool = False,
    ) -> dict:
        transport = manifest.get("transport") or {}
        if transport.get("mode") != "server_gpkg_editable_snapshot":
            raise RuntimeError("지원하지 않는 GeoFlow QGIS transport입니다.")
        if transport.get("direct_postgis_credentials_exposed"):
            raise RuntimeError("안전하지 않은 DB credential manifest를 거부했습니다.")

        package_url = str(transport.get("package_url") or "")
        if not package_url:
            raise RuntimeError("GeoFlow GeoPackage URL이 없습니다.")

        project_def = manifest.get("project") or {}
        project_id = str(project_def.get("id") or "")
        project_code = str(project_def.get("code") or project_id[:8] or "PROJECT")
        if not project_id:
            raise RuntimeError("GeoFlow project id가 없습니다.")

        write_authorized = bool(
            transport.get("local_editing_supported")
            and transport.get("write_authorized")
        )
        changeset_supported = bool(
            write_authorized
            and transport.get("changeset_supported")
            and transport.get("changeset_url")
            and transport.get("delta_url")
        )
        fallback_sync_supported = False
        sync_supported = bool(changeset_supported)
        # Online-only editing requires the atomic changeset endpoint.  The old
        # whole-GeoPackage fallback committed locally before server success.
        can_write = bool(write_authorized and changeset_supported)

        app_root = self._app_data_location()
        project_dir = os.path.join(
            app_root,
            "GeoFlowConnector",
            "projects",
            self._safe_name(project_id),
        )
        os.makedirs(project_dir, exist_ok=True)

        cache_candidate = None
        if changeset_supported and not _force_snapshot:
            cache_candidate = select_reusable_snapshot(project_dir, manifest)

        cache_reused = cache_candidate is not None
        if cache_candidate is not None:
            package_path = cache_candidate.path
            package_size = cache_candidate.size_bytes
        else:
            stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
            package_name = (
                f"geoflow-{self._safe_name(project_code)}-{stamp}.gpkg"
            )
            package_path = os.path.join(project_dir, package_name)
            raw = client.get_bytes(package_url)
            if not raw.startswith(b"SQLite format 3\x00"):
                raise RuntimeError(
                    "GeoFlow Server가 유효한 GeoPackage를 반환하지 않았습니다."
                )
            with open(package_path, "wb") as handle:
                handle.write(raw)
            package_size = len(raw)
            stamp_snapshot(package_path, manifest)
        self.log('project_materialize_package_ready')

        qgs_project = QgsProject.instance()
        root = qgs_project.layerTreeRoot()
        group_name = f"GeoFlow · {project_code}"
        if cache_reused:
            stamp_snapshot(package_path, manifest)

        legacy_packages = legacy_queue_packages(project_dir)
        legacy_total = sum(sum(status.values()) for _path, status in legacy_packages)
        if legacy_total:
            setting_key = f"GeoFlowConnector/onlineOnlyQueuePrompted/{project_id}"
            settings = QSettings()
            if not bool(settings.value(setting_key, False, type=bool)):
                choice = QMessageBox.question(
                    self.iface.mainWindow(),
                    "GeoFlow 온라인 전용 전환",
                    f"기존 GeoFlow 로컬 동기화 항목 {legacy_total}건이 있습니다.\n"
                    "온라인 전용 구조에서는 더 이상 자동 전송하지 않습니다.\n\n"
                    "기존 큐 항목을 삭제하시겠습니까?",
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
                    QMessageBox.StandardButton.Cancel,
                )
                settings.setValue(setting_key, True)
                if choice == QMessageBox.StandardButton.Yes:
                    for legacy_path, _status in legacy_packages:
                        clear_legacy_queue(legacy_path)
                    legacy_total = 0
                    self.log("legacy_local_queue_cleared")
                else:
                    self.log(f"legacy_local_queue_retained count={legacy_total}")

        group = root.addGroup(group_name)
        group.setCustomProperty('geoflow/context_owner', project_id)
        domain_groups = {}

        loaded = 0
        combined_extent = None
        managed_layer_ids = []
        for layer_def in manifest.get("layers") or []:
            physical_name = str(layer_def.get("physical_name") or "")
            standard_name = str(
                layer_def.get("standard_name") or physical_name.upper()
            )
            if not physical_name:
                continue

            layer = QgsVectorLayer(
                f"{package_path}|layername={physical_name}",
                layer_def.get("label") or standard_name,
                "ogr",
            )
            if not layer.isValid():
                raise RuntimeError(
                    f"{standard_name}: GeoPackage 레이어 생성에 실패했습니다."
                )

            self._configure_layer_fields(
                layer,
                layer_def,
                project_id,
                can_write,
            )
            layer.setCustomProperty("geoflow/managed", True)
            layer.setCustomProperty("geoflow/project_id", project_id)
            layer.setCustomProperty("geoflow/standard_name", standard_name)
            layer.setCustomProperty("geoflow/physical_name", physical_name)
            layer.setCustomProperty("geoflow/definition_layer_id", str(layer_def.get("id") or ""))
            layer.setCustomProperty("geoflow/package_path", package_path)
            layer.setCustomProperty("geoflow/local_editing", can_write)
            layer.setCustomProperty("geoflow/sync_supported", sync_supported)
            layer.setCustomProperty(
                "geoflow/server_row_count",
                layer_def.get("row_count", -1),
            )

            # A default is only considered for this newly constructed layer,
            # after every GeoFlow identity/runtime property has been attached.
            # Existing layers take the same-project reuse path above and are
            # intentionally never restyled.
            apply_default_qgis_style(layer, standard_name)

            qgs_project.addMapLayer(layer, False)
            self._domain_group(
                group,
                layer_def.get("domain"),
                domain_groups,
            ).addLayer(layer)
            managed_layer_ids.append(layer.id())
            loaded += 1

            if changeset_supported:
                if hasattr(layer, "beforeCommitChanges"):
                    try:
                        self._connect_sync(layer, layer.beforeCommitChanges,
                            lambda *signal_args, lid=layer.id(): self._before_online_commit(
                                lid, *signal_args
                            )
                        )
                    except Exception:
                        pass
                if hasattr(layer, "afterCommitChanges"):
                    try:
                        self._connect_sync(layer, layer.afterCommitChanges,
                            lambda *signal_args, lid=layer.id(): self._after_online_commit(
                                lid, *signal_args
                            )
                        )
                    except Exception:
                        pass
                if hasattr(layer, "afterRollBack"):
                    try:
                        self._connect_sync(
                            layer,
                            layer.afterRollBack,
                            lambda *signal_args, lid=layer.id():
                                self._discard_captured_layer_changes(lid, *signal_args),
                        )
                    except Exception:
                        pass
            if layer.featureCount() > 0:
                extent = layer.extent()
                if not extent.isEmpty():
                    if combined_extent is None:
                        combined_extent = QgsRectangle(extent)
                    else:
                        combined_extent.combineExtentWith(extent)

        self.log(f'project_materialize_layers_loaded count={loaded}')
        self._write_project_metadata(
            qgs_project,
            manifest,
            project_id,
            project_code,
            package_path,
            sync_supported,
            changeset_supported,
        )
        self.active_context = {
            "project_id": project_id,
            "project_code": project_code,
            "package_path": package_path,
            "sync_url": str(transport.get("sync_url") or ""),
            "changeset_url": str(transport.get("changeset_url") or ""),
            "delta_url": str(transport.get("delta_url") or ""),
            "changeset_supported": changeset_supported,
            "fallback_sync_supported": fallback_sync_supported,
            "sync_supported": sync_supported,
            "client_id": self._client_id(),
            "layer_ids": managed_layer_ids,
            "manifest": manifest,
            "snapshot_cache_reused": cache_reused,
        }
        self.active_client = client

        if changeset_supported and not legacy_total:
            try:
                self._pull_clean_snapshot_delta(client, package_path, manifest)
            except RuntimeError as exc:
                # Retain the existing clean-cache expiry recovery. Retire only this
                # staged candidate; the previous active context still belongs to
                # the outer transaction and must survive if the fresh load fails.
                if cache_reused and _SNAPSHOT_REQUIRED_TEXT in str(exc):
                    self._disconnect_sync_layers(managed_layer_ids)
                    qgs_project.removeMapLayers(managed_layer_ids)
                    if not group.findLayers():
                        root.removeChildNode(group)
                    return SnapshotReuseMixin._materialize_project(self, manifest, client, _force_snapshot=True)
                raise
            except Exception:
                raise  # Failed replay is not a successful project switch.

        if combined_extent is not None and not combined_extent.isEmpty():
            self.iface.mapCanvas().setExtent(combined_extent)
            self.iface.mapCanvas().refresh()

        mode_label = "로컬 편집 가능" if can_write else "읽기 전용"
        if changeset_supported:
            sync_label = "Changeset + Delta"
        else:
            sync_label = "서버 동기화 비활성"
        source_label = "로컬 Snapshot 재사용" if cache_reused else "서버 Snapshot"
        recovery_label = f" · 비활성 기존 큐 {legacy_total}건" if legacy_total else ""
        size_mb = package_size / (1024 * 1024)
        self.iface.messageBar().pushMessage(
            "GeoFlow",
            (
                f"{project_code}: {source_label} · 레이어 {loaded}개 · "
                f"{mode_label} · {sync_label}{recovery_label} · {size_mb:.2f} MB"
            ),
            level=Qgis.Success,
            duration=8,
        )
        return {
            "loaded": loaded,
            "sync_supported": sync_supported,
            "cache_reused": cache_reused,
            "legacy_queue_items": legacy_total,
        }
