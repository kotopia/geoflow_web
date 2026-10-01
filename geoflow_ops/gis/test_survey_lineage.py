from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import resolve, reverse

from . import survey_views
from .qgis_sync import SyncRejected
from .survey_reapply import _selection, preview_survey_reapply


class SurveyLineageContractTests(SimpleTestCase):
    project_id = "11111111-1111-4111-8111-111111111401"

    def test_session_routes_are_project_scoped(self):
        expected = {
            "project_survey_sources_api": survey_views.project_survey_sources_api,
            "project_survey_points_api": survey_views.project_survey_points_api,
            "project_survey_reapply_preview_api": survey_views.project_survey_reapply_preview_api,
            "project_survey_reapply_api": survey_views.project_survey_reapply_api,
        }
        for name, view in expected.items():
            with self.subTest(name=name):
                url = reverse(f"gis:{name}", kwargs={"project_id": self.project_id})
                self.assertIs(resolve(url).func, view)

    def test_reapply_requires_explicit_source_or_points(self):
        with self.assertRaises(SyncRejected):
            _selection({})
        source_id, survey_ids = _selection({"source_id": self.project_id})
        self.assertEqual(source_id, self.project_id)
        self.assertEqual(survey_ids, [])

    def test_preview_classifies_link_states_and_plan_mismatch(self):
        rows = [
            ("1", "s1", "layer-1", "f1", None, "POINT", "LINKED"),
            ("2", "s2", "layer-1", "f2", 1, "VERTEX", "MANUALLY_MODIFIED"),
            ("3", "s3", "layer-1", "f3", 2, "VERTEX", "UNLINKED"),
            ("4", "s4", "missing", "f4", None, "POINT", "LINKED"),
        ]
        plan = {"layers": [{"id": "layer-1", "standard_name": "WTL_PIPE_LM", "physical_name": "wtl_pipe_lm"}]}
        with patch("geoflow_ops.gis.survey_reapply._mapping_rows", return_value=rows), \
                patch("geoflow_ops.gis.survey_reapply._target_preview_info", return_value=("POINT", 1, True)):
            result = preview_survey_reapply("tenant", project_id=self.project_id, plan=plan,
                                            payload={"source_id": self.project_id})
        self.assertEqual(result["counts"], {
            "applicable": 1, "manually_modified": 1, "unlinked": 1, "invalid": 1,
        })

    def test_migration_is_additive_and_preserves_facility_tables(self):
        source = Path(__file__).parents[1] / "migrations" / "0044_gis_survey_lineage.py"
        sql = source.read_text(encoding="utf-8")
        self.assertIn("CREATE TABLE IF NOT EXISTS gis.survey_source", sql)
        self.assertIn("ALTER TABLE gis.survey ADD COLUMN IF NOT EXISTS source_id", sql)
        self.assertIn("ALTER TABLE gis.survey_link ADD COLUMN IF NOT EXISTS vertex_index", sql)
        self.assertIn("ON DELETE RESTRICT", sql)
        self.assertNotIn("DROP TABLE", sql.upper())
        self.assertNotIn("feature_survey_map", sql)

    def test_protected_deploy_wires_exact_migration_and_fail_safe_service(self):
        root = Path(__file__).parents[2]
        command = (root / "control" / "management" / "commands" /
                   "deploy_gis_survey_lineage.py").read_text(encoding="utf-8")
        workflow = (root / ".github" / "workflows" /
                    "gis-definition-code-deploy.yml").read_text(encoding="utf-8")
        self.assertIn('MIGRATION = "0044_gis_survey_lineage"', command)
        self.assertIn('DEPENDENCY = "0043_gis_feature_photo_catalog_v2"', command)
        self.assertIn("Explicit --apply required", command)
        self.assertIn("deploy_gis_survey_lineage --apply", workflow)
        self.assertIn("trap on_exit EXIT", workflow)
