"""Focused regression checks for project materialization and Survey isolation."""
import os
import sys
import tempfile
import unittest
import gc
from pathlib import Path
from unittest.mock import Mock, patch

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
PLUGIN_ROOT = Path(__file__).resolve().parents[1]
PACKAGE_PARENT = PLUGIN_ROOT.parent
if str(PACKAGE_PARENT) not in sys.path:
    sys.path.insert(0, str(PACKAGE_PARENT))

from qgis.core import (
    QgsApplication, QgsFeature, QgsVectorFileWriter, QgsVectorLayer,
    QgsCoordinateTransformContext,
)

from geoflow_connector.app.survey_integration import SurveyIntegrationMixin
from geoflow_connector.cache.reuse import SnapshotReuseMixin
from geoflow_connector.sync.delta_apply import DeltaApplyMixin


class CleanSnapshotDeltaTests(unittest.TestCase):
    def setUp(self):
        self.subject = object.__new__(SnapshotReuseMixin)
        self.subject.log = Mock()
        self.subject._pull_and_apply_delta = Mock(return_value=58)
        self.subject._refresh_local_baseline = Mock()

    def test_server_delta_refreshes_recovery_baseline(self):
        manifest = {"project": {"id": "project"}}
        received = self.subject._pull_clean_snapshot_delta(
            object(), "snapshot.gpkg", manifest)
        self.assertEqual(received, 58)
        self.subject._refresh_local_baseline.assert_called_once_with(
            "snapshot.gpkg", manifest)

    def test_failed_delta_does_not_refresh_baseline(self):
        self.subject._pull_and_apply_delta.side_effect = RuntimeError("delta failed")
        with self.assertRaisesRegex(RuntimeError, "delta failed"):
            self.subject._pull_clean_snapshot_delta(object(), "snapshot.gpkg", {})
        self.subject._refresh_local_baseline.assert_not_called()

class SurveyIsolationTests(unittest.TestCase):
    def test_survey_mixin_does_not_intercept_materialization(self):
        self.assertNotIn("_materialize_project", SurveyIntegrationMixin.__dict__)


class SurveyDeltaPersistenceTests(unittest.TestCase):
    def test_server_authoritative_fields_survive_geopackage_reopen(self):
        survey_id = "50000000-0000-4000-8000-000000000001"
        fields = (
            "field=id:string&field=survey_no:string&field=type:string&"
            "field=raw_x:double&field=raw_y:double&field=raw_z:double&"
            "field=x:double&field=y:double&field=z:double&"
            "field=latitude:double&field=longitude:double&"
            "field=antenna_height:double"
        )
        source = QgsVectorLayer(
            f"Point?crs=EPSG:4326&{fields}", "survey", "memory")
        feature = QgsFeature(source.fields())
        feature.setAttribute("id", survey_id)
        self.assertTrue(source.dataProvider().addFeature(feature))

        with tempfile.TemporaryDirectory() as folder:
            package = str(Path(folder) / "survey.gpkg")
            options = QgsVectorFileWriter.SaveVectorOptions()
            options.driverName = "GPKG"
            options.layerName = "survey"
            status, message, _file, _layer = QgsVectorFileWriter.writeAsVectorFormatV3(
                source, package, QgsCoordinateTransformContext(), options)
            self.assertEqual(status, QgsVectorFileWriter.WriterError.NoError,
                             message)

            layer = QgsVectorLayer(
                f"{package}|layername=survey", "survey", "ogr")
            self.assertTrue(layer.isValid())
            layer.setCustomProperty("geoflow/standard_name", "survey")

            class Subject(DeltaApplyMixin):
                active_context = {"project_id":
                                  "10000000-0000-4000-8000-000000000001"}
                _change_origin = "USER_EDIT"
                _suppress_auto_sync = False

                def _managed_layers(self):
                    return [layer]

                @staticmethod
                def _field_index(target, name):
                    return target.fields().indexFromName(name)

                @staticmethod
                def _delta_value(value):
                    return value

                @staticmethod
                def _geometry_from_hex(_value):
                    return None

            final = {
                "survey_no": "261017-025", "type": "GNSS",
                "raw_x": 236398.45, "raw_y": 408156.62, "raw_z": 49.196,
                "x": 236398.45, "y": 408156.62, "z": 49.196,
                "latitude": 36.2706871, "longitude": 127.4050808,
                "antenna_height": 2.069,
            }
            Subject()._apply_delta_page([{
                "action": "update", "layer": "survey", "id": survey_id,
                "attributes": final,
            }])

            reopened = QgsVectorLayer(
                f"{package}|layername=survey", "reopened-survey", "ogr")
            self.assertTrue(reopened.isValid())
            persisted = next(reopened.getFeatures())
            for name, expected in final.items():
                actual = persisted[name]
                if isinstance(expected, float):
                    self.assertAlmostEqual(actual, expected, places=7, msg=name)
                else:
                    self.assertEqual(actual, expected, name)
            del persisted, reopened, Subject, layer, source
            gc.collect()


if __name__ == "__main__":
    application = QgsApplication([], False)
    application.initQgis()
    try:
        unittest.main(verbosity=2)
    finally:
        application.exitQgis()
