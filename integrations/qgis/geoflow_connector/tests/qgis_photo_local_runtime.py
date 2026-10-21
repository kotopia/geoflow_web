"""QGIS runtime proof that photo pending state is transient and online-only."""
import sqlite3
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from qgis.PyQt.QtWidgets import QLabel
from qgis.core import QgsApplication, QgsFeature, QgsVectorLayer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geoflow_connector.sync.online import legacy_queue_status
from geoflow_connector.ui.photo_section import PhotoSection


APP = QgsApplication.instance() or QgsApplication([], False)
APP.initQgis()

PROJECT_ID, LAYER_ID, OBJECT_ID = str(uuid4()), str(uuid4()), str(uuid4())
policy = {
    "allow_extra_photo": True,
    "templates": [{
        "id": "template", "name": "기본",
        "variants": [{"id": "variant", "name": "기본", "slots": []}],
    }],
}

with tempfile.TemporaryDirectory() as folder:
    package_path = str(Path(folder) / "photo.gpkg")
    connection = sqlite3.connect(package_path)
    connection.execute("CREATE TABLE _geoflow_package(key TEXT PRIMARY KEY,value TEXT)")
    connection.commit()
    connection.close()

    layer = QgsVectorLayer("Point?field=id:string", "photo-online", "memory")
    layer.setCustomProperty("geoflow/managed", True)
    layer.setCustomProperty("geoflow/definition_layer_id", LAYER_ID)
    layer.setCustomProperty("geoflow/standard_name", "WTL_PIPE_PS")
    assert layer.startEditing()
    feature = QgsFeature(layer.fields())
    feature["id"] = OBJECT_ID
    assert layer.addFeature(feature)

    client = Mock()
    client.get_json.return_value = {"photos": []}
    service = SimpleNamespace(
        state="ready", project_id=PROJECT_ID, revision="test",
        policy=lambda _layer_id: policy,
    )
    page = SimpleNamespace(
        note=QLabel(), update_dirty=lambda: None,
        binding=SimpleNamespace(can_save=True, feature_id=feature.id()),
    )
    plugin = SimpleNamespace(
        active_context={
            "package_path": package_path,
            "manifest": {"project": {"id": PROJECT_ID}},
        },
        active_client=client,
        _photo_policy_service=service,
    )
    section = PhotoSection(plugin, page, layer)

    # Unsaved create: no server photo read and no persistent fallback queue.
    section.set_feature(layer.getFeature(feature.id()))
    assert section._server_lookup_deferred
    client.get_json.assert_not_called()
    operation = {
        "local_id": "pending:" + str(uuid4()),
        "template_id": "template", "variant_id": "variant", "slot_id": None,
        "title": "", "note": "", "data": b"normalized-photo",
        "mime_type": "image/jpeg", "original_name": "field.jpg",
        "extra_data": {}, "captured_at": None, "image_metadata": {},
        "signed": None, "uploaded": False, "edit_bytes": None,
        "edit_data": None,
    }
    section.pending_add.append(operation)
    deferred = section.commit_pending()
    assert deferred["ok"] is False and deferred["deferred"] is True
    assert section.pending_add == [operation]
    assert sum(legacy_queue_status(package_path).values()) == 0

    # A new section (restart equivalent) cannot restore transient photo bytes.
    restarted = PhotoSection(plugin, page, layer)
    restarted.set_feature(layer.getFeature(feature.id()))
    assert restarted.pending_add == []

    # Once the feature is committed/server-addressable, upload + relation are direct.
    assert layer.commitChanges(False)
    saved = next(layer.getFeatures())
    page.binding.feature_id = saved.id()
    section.set_feature(saved)
    photo_id = str(uuid4())
    client.post_json.side_effect = lambda _path, payload: (
        {"id": photo_id, "presigned_url": "https://storage.invalid/upload", "headers": {}}
        if payload["action"] == "presign" else {"ok": True}
    )
    uploaded = section.commit_pending()
    assert uploaded["ok"] is True and uploaded["completed"] == 1, uploaded
    assert section.pending_add == []
    client.put_presigned_bytes.assert_called_once()
    assert sum(legacy_queue_status(package_path).values()) == 0

    # A direct upload failure remains only in memory for explicit retry.
    retry = dict(operation)
    retry.update(
        local_id="pending:" + str(uuid4()), signed=None, uploaded=False,
        finalized_id=None,
    )
    section.pending_add.append(retry)
    client.post_json.side_effect = RuntimeError("network down")
    failed = section.commit_pending()
    assert failed["ok"] is False and section.pending_add == [retry]
    assert sum(legacy_queue_status(package_path).values()) == 0

    restarted.deleteLater()
    section.deleteLater()

print("qgis photo online-only runtime: OK")
