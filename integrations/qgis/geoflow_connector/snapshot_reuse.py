from __future__ import annotations

import datetime as dt
import os

from qgis.core import QgsProject, QgsRectangle, QgsVectorLayer, Qgis

from .changeset_queue import (
    ensure_changeset_tables,
    outbox_count,
    pending_count,
)
from .snapshot_cache import select_reusable_snapshot, stamp_snapshot


_SNAPSHOT_REQUIRED_TEXT = "서버 Delta 보존 범위를 벗어났습니다."


class SnapshotReuseMixin:
    """Open a valid local project Snapshot and catch up with Delta only.

    The first open still downloads a server GeoPackage. Later opens validate the
    cached package against the current project/profile/layer schema and reuse it
    in place. A cache carrying pending/outbox work is preferred so offline edits
    are never silently replaced by a fresh Snapshot.
    """

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

        can_write = bool(
            transport.get("local_editing_supported")
            and transport.get("write_authorized")
        )
        changeset_supported = bool(
            can_write
            and transport.get("changeset_supported")
            and transport.get("changeset_url")
            and transport.get("delta_url")
        )
        fallback_sync_supported = bool(
            can_write
            and transport.get("sync_supported")
            and transport.get("sync_url")
            and not changeset_supported
        )
        sync_supported = bool(changeset_supported or fallback_sync_supported)

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
            if changeset_supported:
                ensure_changeset_tables(package_path)
            stamp_snapshot(package_path, manifest)

        qgs_project = QgsProject.instance()
        root = qgs_project.layerTreeRoot()
        group_name = f"GeoFlow · {project_code}"
        old_group = root.findGroup(group_name)
        if old_group is not None:
            old_layer_ids = [node.layerId() for node in old_group.findLayers()]
            if old_layer_ids:
                qgs_project.removeMapLayers(old_layer_ids)
            root.removeChildNode(old_group)

        # Do not write cache metadata while an older QGIS layer instance still
        # has this GeoPackage open. Once the previous group is removed, it is
        # safe to ensure queue tables and mark the cache as recently opened.
        if cache_reused:
            if changeset_supported:
                ensure_changeset_tables(package_path)
            stamp_snapshot(package_path, manifest)

        group = root.addGroup(group_name)
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
            layer.setCustomProperty("geoflow/package_path", package_path)
            layer.setCustomProperty("geoflow/local_editing", can_write)
            layer.setCustomProperty("geoflow/sync_supported", sync_supported)
            layer.setCustomProperty(
                "geoflow/server_row_count",
                layer_def.get("row_count", -1),
            )

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
                        layer.beforeCommitChanges.connect(
                            lambda *signal_args, lid=layer.id(): self._capture_layer_changes(
                                lid, *signal_args
                            )
                        )
                    except Exception:
                        pass
                if hasattr(layer, "afterCommitChanges"):
                    try:
                        layer.afterCommitChanges.connect(
                            lambda *signal_args, lid=layer.id(): self._after_layer_commit(
                                lid, *signal_args
                            )
                        )
                    except Exception:
                        pass
            elif fallback_sync_supported and hasattr(layer, "afterCommitChanges"):
                try:
                    layer.afterCommitChanges.connect(self._schedule_auto_sync)
                except Exception:
                    pass

            if layer.featureCount() > 0:
                extent = layer.extent()
                if not extent.isEmpty():
                    if combined_extent is None:
                        combined_extent = QgsRectangle(extent)
                    else:
                        combined_extent.combineExtentWith(extent)

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

        if changeset_supported:
            try:
                if cache_reused and cache_candidate and cache_candidate.dirty:
                    self._sync_changesets(client)
                else:
                    self._pull_and_apply_delta(client)
            except RuntimeError as exc:
                # A clean cache outside retained Delta history is disposable.
                # If this cache had offline work, _sync_changesets has already
                # attempted to persist it before reaching the Delta pull. Only
                # replace the cache once no pending/outbox work remains.
                if (
                    cache_reused
                    and _SNAPSHOT_REQUIRED_TEXT in str(exc)
                    and pending_count(package_path) == 0
                    and outbox_count(package_path) == 0
                ):
                    self.iface.messageBar().pushMessage(
                        "GeoFlow",
                        "로컬 Snapshot이 Delta 보존 범위를 벗어나 최신 Snapshot으로 교체합니다.",
                        level=Qgis.Info,
                        duration=6,
                    )
                    return SnapshotReuseMixin._materialize_project(
                        self,
                        manifest,
                        client,
                        _force_snapshot=True,
                    )
                self.iface.messageBar().pushMessage(
                    "GeoFlow 최신 변경 수신 실패",
                    str(exc),
                    level=Qgis.Warning,
                    duration=10,
                )
            except Exception as exc:
                self.iface.messageBar().pushMessage(
                    "GeoFlow 최신 변경 수신 실패",
                    str(exc),
                    level=Qgis.Warning,
                    duration=10,
                )

        if combined_extent is not None and not combined_extent.isEmpty():
            self.iface.mapCanvas().setExtent(combined_extent)
            self.iface.mapCanvas().refresh()

        mode_label = "로컬 편집 가능" if can_write else "읽기 전용"
        if changeset_supported:
            sync_label = "Changeset + Delta"
        elif fallback_sync_supported:
            sync_label = "GeoPackage fallback sync"
        else:
            sync_label = "서버 동기화 비활성"
        source_label = "로컬 Snapshot 재사용" if cache_reused else "서버 Snapshot"
        size_mb = package_size / (1024 * 1024)
        self.iface.messageBar().pushMessage(
            "GeoFlow",
            (
                f"{project_code}: {source_label} · 레이어 {loaded}개 · "
                f"{mode_label} · {sync_label} · {size_mb:.2f} MB"
            ),
            level=Qgis.Success,
            duration=8,
        )
        return {
            "loaded": loaded,
            "sync_supported": sync_supported,
            "cache_reused": cache_reused,
        }
