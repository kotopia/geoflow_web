"""QGIS 4.2.2 proof for online-only commit and native multi-delete."""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from qgis.PyQt.QtWidgets import QApplication
from qgis.core import (
    QgsApplication, QgsFeature, QgsGeometry, QgsPointXY, QgsProject,
    QgsVectorLayer, Qgis,
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geoflow_connector.api.client import GeoFlowChangesetConflict
from geoflow_connector.app.plugin import GeoFlowConnectorPlugin
from geoflow_connector.sync.online import (
    LEGACY_QUEUE_TABLES, clear_legacy_queue, legacy_queue_status,
)


APP = QApplication.instance() or QgsApplication([], False)
if isinstance(APP, QgsApplication):
    APP.initQgis()


class MessageBar:
    def __init__(self):
        self.messages = []

    def pushMessage(self, *args, **kwargs):
        self.messages.append((args, kwargs))


def create_fixture(feature_count=3):
    temporary = tempfile.TemporaryDirectory()
    package_path = str(Path(temporary.name) / "online.gpkg")
    object_ids = [str(uuid4()) for _ in range(feature_count)]
    connection = sqlite3.connect(package_path)
    connection.execute("CREATE TABLE _geoflow_package(key TEXT PRIMARY KEY,value TEXT)")
    connection.execute(
        "INSERT INTO _geoflow_package(key,value) VALUES ('last_applied_revision','17')"
    )
    connection.execute("CREATE TABLE test_points(fid INTEGER PRIMARY KEY,id TEXT,value TEXT)")
    connection.executemany(
        "INSERT INTO test_points(fid,id,value) VALUES (?,?,?)",
        [(index + 1, object_id, f"v{index + 1}") for index, object_id in enumerate(object_ids)],
    )
    connection.commit()
    connection.close()

    layer = QgsVectorLayer("Point?field=id:string&field=value:string", "온라인 테스트", "memory")
    for index, object_id in enumerate(object_ids):
        feature = QgsFeature(layer.fields())
        feature["id"] = object_id
        feature["value"] = f"v{index + 1}"
        assert layer.dataProvider().addFeature(feature)
    layer.setCustomProperty("geoflow/managed", True)
    layer.setCustomProperty("geoflow/standard_name", "TEST_POINTS")
    layer.setCustomProperty("geoflow/physical_name", "test_points")
    QgsProject.instance().addMapLayer(layer)

    bar = MessageBar()
    plugin = GeoFlowConnectorPlugin(
        SimpleNamespace(messageBar=lambda: bar, mainWindow=lambda: None)
    )
    client = Mock()
    plugin.active_client = client
    plugin.active_context = {
        "package_path": package_path,
        "changeset_supported": True,
        "sync_supported": True,
        "changeset_url": "/api/projects/p/changesets/",
        "delta_url": "/api/projects/p/delta/",
        "client_id": str(uuid4()),
        "layer_ids": [layer.id()],
        "manifest": {"layers": [{
            "standard_name": "TEST_POINTS", "physical_name": "test_points",
            "fields": [
                {"name": "id", "editable": False},
                {"name": "value", "editable": True},
            ],
        }]},
    }
    layer.beforeCommitChanges.connect(
        lambda *args, lid=layer.id(): plugin._before_online_commit(lid, *args)
    )
    layer.afterCommitChanges.connect(
        lambda *args, lid=layer.id(): plugin._after_online_commit(lid, *args)
    )
    layer.afterRollBack.connect(
        lambda *args, lid=layer.id(): plugin._discard_captured_layer_changes(lid, *args)
    )
    return temporary, package_path, object_ids, layer, plugin, client, bar


temporary, package_path, object_ids, layer, plugin, client, bar = create_fixture()
try:
    # Core case: three native DELETEs, server failure, buffer remains, retry succeeds.
    assert layer.startEditing()
    fids = [feature.id() for feature in layer.getFeatures()]
    assert len(fids) == 3 and layer.deleteFeatures(fids)
    client.post_json.side_effect = [
        RuntimeError("HTTP 503"),
        {"ok": True, "created": 0, "updated": 0, "deleted": 3,
         "total": 3, "new_revision": 18},
    ]

    provider_calls = []
    layer.beforeCommitChanges.connect(lambda *_args: provider_calls.append(True))
    first_commit = plugin.commit_layer_online(layer, stop_editing=False)
    assert not first_commit["ok"]
    assert not first_commit["provider_commit_called"]
    assert provider_calls == []
    assert layer.isEditable() and layer.isModified()
    assert set(layer.editBuffer().deletedFeatureIds()) == set(fids)
    assert sum(legacy_queue_status(package_path).values()) == 0
    assert client.post_json.call_count == 1
    first_payload = client.post_json.call_args_list[0].args[1]
    assert [row["action"] for row in first_payload["changes"]] == ["delete"] * 3
    assert {row["id"] for row in first_payload["changes"]} == set(object_ids)

    second_commit = plugin.commit_layer_online(layer, stop_editing=False)
    assert second_commit["ok"]
    assert second_commit["provider_commit_called"]
    assert len(provider_calls) == 1
    assert not layer.isModified() and layer.featureCount() == 0
    assert client.post_json.call_count == 2
    second_payload = client.post_json.call_args_list[1].args[1]
    assert second_payload["changeset_id"] == first_payload["changeset_id"]
    assert sum(legacy_queue_status(package_path).values()) == 0
    check = sqlite3.connect(package_path)
    try:
        table_names = {
            row[0] for row in check.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
    finally:
        check.close()
    assert all(table not in table_names for table in LEGACY_QUEUE_TABLES)

    # Same single-layer pipeline and one changeset for small/large multi-delete.
    for delete_count in (2, 10):
        batch_temp, _batch_path, batch_ids, batch_layer, batch_plugin, batch_client, _ = (
            create_fixture(delete_count)
        )
        try:
            assert batch_layer.startEditing()
            batch_fids = [row.id() for row in batch_layer.getFeatures()]
            assert len(batch_fids) == delete_count
            assert batch_layer.deleteFeatures(batch_fids)
            batch_client.post_json.return_value = {
                "ok": True, "created": 0, "updated": 0,
                "deleted": delete_count, "total": delete_count,
                "new_revision": 18,
            }
            batch_result = batch_plugin.commit_layer_online(batch_layer)
            assert batch_result["ok"]
            assert batch_result["operation_counts"]["delete"] == delete_count
            assert batch_client.post_json.call_count == 1
            batch_payload = batch_client.post_json.call_args.args[1]
            assert len(batch_payload["changes"]) == delete_count
            assert {row["id"] for row in batch_payload["changes"]} == set(batch_ids)
        finally:
            QgsProject.instance().removeMapLayer(batch_layer.id())
            batch_temp.cleanup()

    # Conflict: commit is blocked immediately and no conflict row is persisted.
    conflict_temp, conflict_path, _, conflict_layer, conflict_plugin, conflict_client, conflict_bar = create_fixture()
    try:
        assert conflict_layer.startEditing()
        feature = next(conflict_layer.getFeatures())
        value_index = conflict_layer.fields().indexFromName("value")
        assert conflict_layer.changeAttributeValue(feature.id(), value_index, "changed")
        conflict_client.post_json.side_effect = [
            GeoFlowChangesetConflict(
                "revision conflict",
                conflicts=[{"reason": "revision_conflict", "id": feature["id"]}],
                payload={"current_revision": 18},
            ),
            {"ok": True, "created": 0, "updated": 1, "deleted": 0,
             "total": 1, "new_revision": 19},
        ]
        conflict_provider_calls = []
        conflict_layer.beforeCommitChanges.connect(
            lambda *_args: conflict_provider_calls.append(True)
        )
        conflict_result = conflict_plugin.commit_layer_online(
            conflict_layer, stop_editing=False
        )
        assert not conflict_result["ok"]
        assert not conflict_result["provider_commit_called"]
        assert conflict_provider_calls == []
        assert conflict_layer.isEditable() and conflict_layer.isModified()
        assert sum(legacy_queue_status(conflict_path).values()) == 0
        assert any("서버 충돌" in str(message[0]) for message in conflict_bar.messages)
        retry_result = conflict_plugin.commit_layer_online(conflict_layer)
        assert retry_result["ok"]
        assert len(conflict_provider_calls) == 1
    finally:
        QgsProject.instance().removeMapLayer(conflict_layer.id())
        conflict_temp.cleanup()

    # A save action which requests editing to stop must still retain failures.
    stop_temp, stop_path, _, stop_layer, stop_plugin, stop_client, _ = create_fixture()
    try:
        assert stop_layer.startEditing()
        stop_fid = next(stop_layer.getFeatures()).id()
        assert stop_layer.deleteFeature(stop_fid)
        stop_client.post_json.side_effect = RuntimeError("network down")
        stop_provider_calls = []
        stop_layer.beforeCommitChanges.connect(
            lambda *_args: stop_provider_calls.append(True)
        )
        stop_result = stop_plugin.commit_layer_online(
            stop_layer, stop_editing=True
        )
        APP.processEvents()
        assert not stop_result["ok"]
        assert not stop_result["provider_commit_called"]
        assert stop_provider_calls == []
        assert stop_layer.isEditable() and stop_layer.isModified()
        assert stop_fid in set(stop_layer.editBuffer().deletedFeatureIds())
        assert sum(legacy_queue_status(stop_path).values()) == 0
        stop_layer.rollBack()
    finally:
        QgsProject.instance().removeMapLayer(stop_layer.id())
        stop_temp.cleanup()

    # One explicit save batches CREATE A/B + DELETE C + UPDATE D.
    batch_temp, batch_path, _, batch_layer, batch_plugin, batch_client, _ = create_fixture()
    try:
        assert batch_layer.startEditing()
        existing = list(batch_layer.getFeatures())
        value_index = batch_layer.fields().indexFromName("value")
        assert batch_layer.deleteFeature(existing[0].id())
        assert batch_layer.changeAttributeValue(existing[1].id(), value_index, "updated")
        assert batch_layer.changeGeometry(
            existing[1].id(), QgsGeometry.fromPointXY(QgsPointXY(10, 10))
        )
        for coordinate, label in enumerate(("created-a", "created-b"), 20):
            created = QgsFeature(batch_layer.fields())
            created["id"] = str(uuid4())
            created["value"] = label
            created.setGeometry(QgsGeometry.fromPointXY(
                QgsPointXY(coordinate, coordinate)
            ))
            assert batch_layer.addFeature(created)
        batch_client.post_json.return_value = {
            "ok": True, "created": 2, "updated": 1, "deleted": 1,
            "total": 4, "new_revision": 18,
        }
        batch_result = batch_plugin.commit_layer_online(batch_layer)
        assert batch_result["ok"]
        assert batch_result["operation_counts"] == {
            "create": 2, "update": 1, "delete": 1,
        }
        assert batch_client.post_json.call_count == 1
        batch_payload = batch_client.post_json.call_args.args[1]
        assert len({batch_payload["changeset_id"]}) == 1
        assert len(batch_payload["changes"]) == 4
    finally:
        if batch_layer.isEditable():
            batch_layer.rollBack()
        QgsProject.instance().removeMapLayer(batch_layer.id())
        batch_temp.cleanup()

    # Facility and depth layers are posted as one server changeset before
    # either provider receives a commit call.
    atomic_temp, _, _, facility_layer, atomic_plugin, atomic_client, _ = create_fixture()
    depth_layer = QgsVectorLayer(
        "Point?field=id:string&field=pip_dep:double", "depth", "memory"
    )
    depth_layer.setCustomProperty("geoflow/managed", True)
    depth_layer.setCustomProperty("geoflow/standard_name", "WTL_PIPE_PS")
    depth_layer.setCustomProperty("geoflow/physical_name", "wtl_pipe_ps")
    QgsProject.instance().addMapLayer(depth_layer)
    atomic_plugin.active_context["manifest"]["layers"].append({
        "standard_name": "WTL_PIPE_PS", "physical_name": "wtl_pipe_ps",
        "fields": [{"name": "id", "editable": False},
                   {"name": "pip_dep", "editable": True}],
    })
    try:
        assert facility_layer.startEditing() and depth_layer.startEditing()
        for index in range(10):
            facility = QgsFeature(facility_layer.fields())
            facility["id"] = str(uuid4())
            facility["value"] = "facility"
            facility.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(index, 1)))
            depth = QgsFeature(depth_layer.fields())
            depth["id"] = str(uuid4())
            depth["pip_dep"] = 1.25
            depth.setGeometry(QgsGeometry.fromPointXY(QgsPointXY(index, 1)))
            assert facility_layer.addFeature(facility)
            assert depth_layer.addFeature(depth)
        provider_order = []
        facility_layer.beforeCommitChanges.connect(
            lambda *_args: provider_order.append("facility")
        )
        depth_layer.beforeCommitChanges.connect(
            lambda *_args: provider_order.append("depth")
        )
        atomic_client.post_json.return_value = {
            "ok": True, "created": 20, "updated": 0, "deleted": 0,
            "total": 20, "new_revision": 18,
        }
        atomic_result = atomic_plugin.commit_layers_online(
            [facility_layer, depth_layer],
            trigger="survey_batch_create",
        )
        assert atomic_result["ok"]
        atomic_payload = atomic_client.post_json.call_args.args[1]
        assert len(atomic_payload["changes"]) == 20
        assert atomic_result["operation_counts"] == {
            "create": 20, "update": 0, "delete": 0,
        }
        assert atomic_client.post_json.call_count == 1
        assert {row["layer"] for row in atomic_payload["changes"]} == {
            "TEST_POINTS", "WTL_PIPE_PS",
        }
        assert provider_order == ["facility", "depth"]
    finally:
        for atomic_layer in (facility_layer, depth_layer):
            if atomic_layer.isEditable():
                atomic_layer.rollBack()
            QgsProject.instance().removeMapLayer(atomic_layer.id())
        atomic_temp.cleanup()

    # Legacy rows are inert and removed only by the explicit migration action.
    migration_path = str(Path(temporary.name) / "legacy.gpkg")
    connection = sqlite3.connect(migration_path)
    connection.execute("CREATE TABLE _geoflow_pending_change(value TEXT)")
    connection.execute("INSERT INTO _geoflow_pending_change(value) VALUES ('stale')")
    connection.commit()
    connection.close()
    assert sum(legacy_queue_status(migration_path).values()) == 1
    assert clear_legacy_queue(migration_path) == 1
    assert sum(legacy_queue_status(migration_path).values()) == 0

    result = {
        "qgis_version": Qgis.QGIS_VERSION,
        "multi_delete": 3,
        "failed_commit_preserved_buffer": True,
        "failed_provider_commit_calls": 0,
        "retry_succeeded": True,
        "same_transient_changeset_id": True,
        "mixed_geometry_batch_one_changeset": True,
        "facility_depth_atomic_server_changeset": True,
        "persistent_queue_rows": 0,
        "persistent_queue_tables_created": False,
        "conflict_preserved_buffer": True,
        "conflict_provider_commit_calls": 0,
        "conflict_buffer_retry_succeeded": True,
        "stop_editing_failure_preserved_buffer": True,
        "legacy_cleanup_requires_explicit_call": True,
    }
    print("qgis online-only commit runtime: " + json.dumps(result, ensure_ascii=False))
finally:
    if layer.isEditable():
        layer.rollBack()
    QgsProject.instance().removeMapLayer(layer.id())
    temporary.cleanup()
