"""QGIS 4.2.2 proof for the GeoFlow delete-button lifecycle."""
import json
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from qgis.core import QgsApplication, QgsFeature, QgsProject, QgsVectorLayer, Qgis

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geoflow_connector.app.plugin import GeoFlowConnectorPlugin
from geoflow_connector.api.client import GeoFlowChangesetConflict
from geoflow_connector.ui.edit_tools import EditToolsController
from geoflow_connector.ui.form_host import Main as DynamicFormHost


APP = QgsApplication.instance() or QgsApplication([], False)
if isinstance(APP, QgsApplication):
    APP.initQgis()


class DeleteAction:
    def __init__(self, layer):
        self.layer = layer

    def trigger(self):
        self.layer.deleteFeatures(self.layer.selectedFeatureIds())


class Work:
    def __init__(self):
        self.cleared = []

    def complete_committed_delete(self, layer_id, ids):
        self.cleared.append((layer_id, list(ids)))
        return True


class Workspace:
    def __init__(self):
        self.refreshed = 0

    def refresh(self):
        self.refreshed += 1


class Harness:
    def __init__(self, plugin, layer):
        self.plugin = plugin
        self.layer = layer
        self.messages = []
        self.refreshed = 0

    def _active_layer(self):
        return self.layer

    def _is_managed_edit_layer(self, layer):
        return layer is self.layer

    def _iface_action(self, *_names):
        return DeleteAction(self.layer)

    def _set_message(self, message, page=None):
        del page
        self.messages.append(str(message))

    def _log(self, event):
        self.plugin.log(event)

    def _delete_log(self, key, value):
        EditToolsController._delete_log(self, key, value)

    def refresh(self):
        self.refreshed += 1


def fixture(server_result, *, survey_generated=False):
    temporary = tempfile.TemporaryDirectory()
    package_path = str(Path(temporary.name) / "delete.gpkg")
    object_id = str(uuid4())
    connection = sqlite3.connect(package_path)
    connection.execute("CREATE TABLE _geoflow_package(key TEXT PRIMARY KEY,value TEXT)")
    connection.execute("INSERT INTO _geoflow_package VALUES ('last_applied_revision','1')")
    connection.execute("CREATE TABLE target(fid INTEGER PRIMARY KEY,id TEXT,value TEXT)")
    connection.execute("INSERT INTO target VALUES (1,?,?)", (object_id, "value"))
    connection.commit()
    connection.close()

    layer = QgsVectorLayer(
        "Point?field=id:string&field=value:string&field=survey_id:string",
        "delete", "memory"
    )
    feature = QgsFeature(layer.fields())
    feature["id"] = object_id
    feature["value"] = "value"
    if survey_generated:
        feature["survey_id"] = str(uuid4())
    assert layer.dataProvider().addFeature(feature)
    layer.setCustomProperty("geoflow/managed", True)
    layer.setCustomProperty("geoflow/standard_name", "TARGET")
    layer.setCustomProperty("geoflow/physical_name", "target")
    QgsProject.instance().addMapLayer(layer)

    plugin = GeoFlowConnectorPlugin(SimpleNamespace(messageBar=lambda: SimpleNamespace(
        pushMessage=lambda *args, **kwargs: None
    )))
    plugin.active_client = Mock()
    if isinstance(server_result, Exception):
        plugin.active_client.post_json.side_effect = server_result
    else:
        plugin.active_client.post_json.return_value = server_result
    plugin.active_context = {
        "package_path": package_path,
        "changeset_supported": True,
        "changeset_url": "/changesets/",
        "client_id": str(uuid4()),
        "manifest": {"layers": [{
            "standard_name": "TARGET", "physical_name": "target",
            "fields": [{"name": "id", "editable": False},
                       {"name": "value", "editable": True}],
        }]},
    }
    logs = []
    plugin.log = logs.append
    plugin.work = Work()
    plugin._workspace_model = Workspace()
    layer.beforeCommitChanges.connect(
        lambda *args: plugin._before_online_commit(layer.id(), *args)
    )
    layer.afterCommitChanges.connect(
        lambda *args: plugin._after_online_commit(layer.id(), *args)
    )
    return temporary, layer, plugin, logs


success_temp, success_layer, success_plugin, success_logs = fixture({
    "ok": True, "created": 0, "updated": 0, "deleted": 1, "new_revision": 2,
})
failure_temp, failure_layer, failure_plugin, failure_logs = fixture(
    GeoFlowChangesetConflict(
        "delete conflict",
        conflicts=[{
            "layer": "TARGET", "id": "conflicted-id",
            "reason": "delete_protected", "conflict_type": "reference",
            "expected_revision": 8, "actual_revision": 9,
        }],
        payload={
            "code": "delete_conflict", "reason": "delete_protected",
            "message": "target is referenced", "conflict_type": "reference",
            "expected_revision": 8, "current_revision": 9,
        },
    )
)
native_temp, native_layer, native_plugin, native_logs = fixture({
    "ok": True, "created": 0, "updated": 0, "deleted": 1,
    "new_revision": 2,
})
survey_temp, survey_layer, survey_plugin, survey_logs = fixture({
    "ok": True, "created": 0, "updated": 0, "deleted": 1,
    "new_revision": 2,
}, survey_generated=True)
try:
    success_fid = next(success_layer.getFeatures()).id()
    success_layer.selectByIds([success_fid])
    staged = EditToolsController._delete_selected(
        Harness(success_plugin, success_layer)
    )
    assert staged and success_layer.isModified()
    success_plugin._online_save_trigger = "qgis_save_action"
    success_commit = success_plugin.commit_layer_online(success_layer)
    assert success_commit["ok"] and success_commit["provider_commit_called"]
    assert success_layer.featureCount() == 0
    assert not success_layer.isModified()
    success_plugin.work.complete_committed_delete(success_layer.id(), [success_fid])
    assert all(any(f"[DELETE] {key}=" in row for row in success_logs) for key in (
        "action_clicked", "layer", "selected_ids", "qgis_buffer_deleted_ids",
        "changeset_id", "base_revision", "server_revision", "server_result",
        "provider_commit_called", "provider_commit_result",
    ))
    assert all(any(f"[ONLINE_SAVE] {key}=" in row for row in success_logs)
               for key in (
                   "trigger", "layer", "creates", "updates", "deletes",
                   "feature_ids", "base_revision", "server_revision_before",
                   "changeset_id", "server_result", "server_revision_after",
                   "provider_commit_called", "provider_commit_result",
                   "buffer_dirty_after",
               ))
    assert any("[ONLINE_SAVE] trigger=qgis_save_action" in row
               for row in success_logs)
    assert all(any(f"[DELETE_PAYLOAD] {key}=" in row for row in success_logs)
               for key in (
                   "changeset_id", "base_revision", "layer", "feature_id",
                   "operation", "object_revision_field_present",
                   "object_revision_value", "feature_attributes_keys",
               ))
    assert any("[DELETE_PAYLOAD] object_revision_field_present=False" in row
               for row in success_logs)

    # Survey provenance does not select a special DELETE contract or path.
    survey_fid = next(survey_layer.getFeatures()).id()
    assert survey_layer.startEditing()
    assert survey_layer.deleteFeature(survey_fid)
    survey_result = survey_plugin.commit_layer_online(survey_layer)
    assert survey_result["ok"] and survey_result["operation_counts"]["delete"] == 1
    survey_payload = survey_plugin.active_client.post_json.call_args.args[1]
    assert survey_payload["changes"] == [{
        "action": "delete", "layer": "TARGET",
        "id": survey_payload["changes"][0]["id"],
    }]

    failure_fid = next(failure_layer.getFeatures()).id()
    failure_layer.selectByIds([failure_fid])
    staged_failure = EditToolsController._delete_selected(
        Harness(failure_plugin, failure_layer)
    )
    assert staged_failure
    provider_calls = []
    failure_layer.beforeCommitChanges.connect(lambda *args: provider_calls.append(args))
    failed = failure_plugin.commit_layer_online(failure_layer)
    assert not failed["ok"] and not failed["provider_commit_called"]
    assert provider_calls == []
    assert failure_layer.isModified()
    assert failure_fid in set(failure_layer.editBuffer().deletedFeatureIds())
    assert failure_plugin.work.cleared == []
    assert all(any(f"[DELETE_CONFLICT] {key}=" in row for row in failure_logs)
               for key in (
                   "http_status", "error_code", "reason", "message",
                   "conflict_type", "expected_revision", "actual_revision",
                   "raw_response_keys",
               ))
    assert any("[DELETE_CONFLICT] reason=delete_protected" in row
               for row in failure_logs)
    assert any("[DELETE_CONFLICT] expected_revision=8" in row
               for row in failure_logs)
    assert any("[DELETE_CONFLICT] actual_revision=9" in row
               for row in failure_logs)

    # A delete performed by QGIS' own action has no GeoFlow pending property;
    # save_current must discover deletedFeatureIds directly.
    native_fid = next(native_layer.getFeatures()).id()
    assert native_layer.startEditing()
    assert native_layer.deleteFeature(native_fid)
    native_plugin._workspace_model = Workspace()
    adapter = SimpleNamespace(
        selected_layer_id=lambda: native_layer.id(),
        layers_by_id=lambda: {native_layer.id(): native_layer},
    )
    host = SimpleNamespace(
        pages={}, adapter=adapter, plugin=native_plugin,
        complete_committed_delete=lambda *_args: True,
    )
    native_plugin._online_save_trigger = "qgis_save_action"
    assert DynamicFormHost.save_current(host)
    assert native_layer.featureCount() == 0
    assert not native_layer.isModified()

    print("qgis delete action runtime: " + json.dumps({
        "qgis_version": Qgis.QGIS_VERSION,
        "success_server_then_provider": True,
        "conflict_provider_commit_not_called": True,
        "failure_preserved_delete_buffer": True,
        "failure_preserved_form_context": True,
        "lifecycle_logs_complete": True,
        "native_qgis_delete_discovered_on_save": True,
    }, ensure_ascii=False))
finally:
    if failure_layer.isEditable():
        failure_layer.rollBack()
    if native_layer.isEditable():
        native_layer.rollBack()
    if survey_layer.isEditable():
        survey_layer.rollBack()
    for layer in (success_layer, failure_layer, native_layer, survey_layer):
        QgsProject.instance().removeMapLayer(layer.id())
    success_temp.cleanup()
    failure_temp.cleanup()
    native_temp.cleanup()
    survey_temp.cleanup()
    if isinstance(APP, QgsApplication):
        APP.exitQgis()
