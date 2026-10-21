"""QGIS runtime checks for the online-only changeset lifecycle."""
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

from qgis.core import QgsApplication, QgsFeature, QgsGeometry, QgsProject, QgsVectorLayer

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from geoflow_connector.app.plugin import GeoFlowConnectorPlugin
from geoflow_connector.sync.online import legacy_queue_status


class OnlineChangesetRuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.path = str(Path(self.temporary.name) / "online.gpkg")
        connection = sqlite3.connect(self.path)
        connection.execute("CREATE TABLE _geoflow_package(key TEXT PRIMARY KEY,value TEXT)")
        connection.execute(
            "INSERT INTO _geoflow_package(key,value) VALUES ('last_applied_revision','7')"
        )
        connection.execute("CREATE TABLE test_point(fid INTEGER PRIMARY KEY,id TEXT,remark TEXT)")
        connection.commit()
        connection.close()

        self.layer = QgsVectorLayer(
            "Point?crs=EPSG:4326&field=id:string&field=remark:string",
            "Lifecycle", "memory",
        )
        self.layer.setCustomProperty("geoflow/standard_name", "TEST_POINT")
        self.layer.setCustomProperty("geoflow/physical_name", "test_point")
        QgsProject.instance().addMapLayer(self.layer)
        self.bar = SimpleNamespace(pushMessage=Mock())
        self.plugin = GeoFlowConnectorPlugin(
            SimpleNamespace(messageBar=lambda: self.bar, mainWindow=lambda: None)
        )
        self.plugin.active_client = Mock()
        self.plugin.active_context = {
            "changeset_supported": True, "sync_supported": True,
            "changeset_url": "/changesets", "delta_url": "/delta",
            "client_id": str(uuid4()), "package_path": self.path,
            "layer_ids": [self.layer.id()],
            "manifest": {"layers": [{
                "standard_name": "TEST_POINT", "physical_name": "test_point",
                "fields": [
                    {"name": "id", "editable": False},
                    {"name": "remark", "editable": True},
                ],
            }]},
        }
        self.layer.beforeCommitChanges.connect(
            lambda *args: self.plugin._before_online_commit(self.layer.id(), *args)
        )
        self.layer.afterCommitChanges.connect(
            lambda *args: self.plugin._after_online_commit(self.layer.id(), *args)
        )
        self.layer.afterRollBack.connect(
            lambda *args: self.plugin._discard_captured_layer_changes(self.layer.id(), *args)
        )

    def tearDown(self):
        if self.layer.isEditable():
            self.layer.rollBack()
        QgsProject.instance().removeMapLayer(self.layer.id())
        self.temporary.cleanup()

    def _add(self):
        feature = QgsFeature(self.layer.fields())
        feature["id"] = str(uuid4())
        feature["remark"] = "local"
        feature.setGeometry(QgsGeometry.fromWkt("POINT (127 36)"))
        self.assertTrue(self.layer.addFeature(feature))
        return feature

    def test_rollback_never_sends_or_persists(self):
        self.assertTrue(self.layer.startEditing())
        self._add()
        self.assertTrue(self.layer.rollBack())
        self.plugin.active_client.post_json.assert_not_called()
        self.assertEqual(sum(legacy_queue_status(self.path).values()), 0)

    def test_explicit_commit_sends_before_provider_commit(self):
        self.assertTrue(self.layer.startEditing())
        self._add()
        self.plugin.active_client.post_json.return_value = {
            "created": 1, "updated": 0, "deleted": 0, "new_revision": 8,
        }
        self.assertTrue(self.layer.commitChanges(False))
        payload = self.plugin.active_client.post_json.call_args.args[1]
        self.assertEqual([row["action"] for row in payload["changes"]], ["create"])
        self.assertEqual(sum(legacy_queue_status(self.path).values()), 0)

    def test_delete_wins_over_update(self):
        object_id = str(uuid4())
        feature = QgsFeature(self.layer.fields())
        feature["id"], feature["remark"] = object_id, "before"
        feature.setGeometry(QgsGeometry.fromWkt("POINT (127 36)"))
        self.assertTrue(self.layer.dataProvider().addFeature(feature))
        fid = next(self.layer.getFeatures()).id()
        connection = sqlite3.connect(self.path)
        connection.execute(
            "INSERT INTO test_point(fid,id,remark) VALUES (?,?,?)",
            (fid, object_id, "before"),
        )
        connection.commit()
        connection.close()
        self.assertTrue(self.layer.startEditing())
        self.assertTrue(self.layer.changeAttributeValue(
            fid, self.layer.fields().indexFromName("remark"), "after"
        ))
        self.assertTrue(self.layer.deleteFeature(fid))
        changes = self.plugin._capture_layer_changes(self.layer.id())
        self.assertEqual(changes, [{
            "action": "delete", "layer": "TEST_POINT", "id": object_id,
        }])

    def test_manual_refresh_refuses_draft(self):
        self.assertTrue(self.layer.startEditing())
        self._add()
        with self.assertRaisesRegex(RuntimeError, "저장하지 않은 편집"):
            self.plugin._assert_no_draft_edits()
        self.assertTrue(self.layer.isModified())
        self.assertEqual(sum(legacy_queue_status(self.path).values()), 0)


if __name__ == "__main__":
    application = QgsApplication([], False)
    application.initQgis()
    try:
        unittest.main(verbosity=2)
    finally:
        application.exitQgis()
