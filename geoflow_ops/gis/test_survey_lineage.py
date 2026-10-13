from pathlib import Path
from unittest.mock import patch

from django.test import SimpleTestCase
from django.urls import resolve, reverse

from . import survey_views
from .qgis_sync import SyncRejected
from .survey_reapply import _selection, preview_survey_reapply
from .survey_sources import _point_metadata


class SurveyLineageContractTests(SimpleTestCase):
    project_id = "11111111-1111-4111-8111-111111111401"

    def test_session_routes_are_project_scoped(self):
        expected = {
            "project_survey_sources_api": survey_views.project_survey_sources_api,
            "project_survey_source_api": survey_views.project_survey_source_api,
            "project_survey_points_api": survey_views.project_survey_points_api,
            "project_survey_point_api": survey_views.project_survey_point_api,
            "project_survey_points_bulk_delete_api": survey_views.project_survey_points_bulk_delete_api,
            "project_survey_reapply_preview_api": survey_views.project_survey_reapply_preview_api,
            "project_survey_reapply_api": survey_views.project_survey_reapply_api,
        }
        for name, view in expected.items():
            with self.subTest(name=name):
                kwargs = {"project_id": self.project_id}
                if name == "project_survey_source_api":
                    kwargs["source_id"] = "22222222-2222-4222-8222-222222222222"
                elif name == "project_survey_point_api":
                    kwargs["survey_id"] = "22222222-2222-4222-8222-222222222222"
                url = reverse(f"gis:{name}", kwargs=kwargs)
                self.assertIs(resolve(url).func, view)

    def test_survey_point_import_metadata_defaults_and_validation(self):
        metadata = _point_metadata(
            "tenant",
            {"source_row_id": "P001", "raw_code": "DEP", "survey_date": "2026-10-05",
             "pdop": "1.25", "antenna_height": "1.800"},
            {},
            0,
        )
        self.assertEqual(metadata["name"], "P001")
        self.assertEqual(metadata["code"], "DEP")
        self.assertEqual(metadata["survey_date"].isoformat(), "2026-10-05")
        with self.assertRaisesRegex(SyncRejected, "YYYY-MM-DD"):
            _point_metadata(
                "tenant",
                {"source_row_id": "P002", "survey_date": "05/10/2026"}, {}, 1,
            )

    def test_import_workers_use_shared_assignment_authorization(self):
        request = object()
        with patch("geoflow_ops.gis.survey_views.validate_worker_assignment") as validate:
            survey_views._validate_import_workers(
                request,
                "tenant",
                self.project_id,
                {
                    "worker_id": "80000000-0000-4000-8000-000000000001",
                    "points": [
                        {"worker_id": "80000000-0000-4000-8000-000000000001"},
                        {"worker_id": "80000000-0000-4000-8000-000000000002"},
                    ],
                },
            )
        self.assertEqual(validate.call_count, 2)
        self.assertTrue(all(call.args[3] is request for call in validate.call_args_list))
        with self.assertRaisesRegex(SyncRejected, "unsupported fields"):
            _point_metadata(
                "tenant",
                {"source_row_id": "P003", "survey_code": "legacy-guess"}, {}, 2,
            )

    def test_survey_source_delete_policy_is_soft_and_preserves_links(self):
        root = Path(__file__).parents[2]
        sources = (root / "geoflow_ops" / "gis" / "survey_sources.py").read_text(encoding="utf-8")
        self.assertIn("SET deleted_at=now(),deleted_by=%s,delete_reason=%s", sources)
        self.assertIn("facility_links_preserved", sources)
        self.assertIn('"facilities_deleted": 0', sources)
        self.assertNotIn("DELETE FROM gis.survey WHERE", sources)
        self.assertNotIn("DELETE FROM gis.survey_source WHERE", sources)

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
        soft_delete = Path(__file__).parents[1] / "migrations" / "0045_gis_survey_soft_delete.py"
        soft_sql = soft_delete.read_text(encoding="utf-8")
        self.assertIn("ALTER TABLE gis.survey_source ADD COLUMN IF NOT EXISTS deleted_at", soft_sql)
        self.assertIn("ALTER TABLE gis.survey ADD COLUMN IF NOT EXISTS deleted_at", soft_sql)
        self.assertNotIn("CASCADE", soft_sql.upper())

    def test_protected_deploy_wires_exact_migration_and_fail_safe_service(self):
        root = Path(__file__).parents[2]
        command = (root / "control" / "management" / "commands" /
                   "deploy_gis_survey_lineage.py").read_text(encoding="utf-8")
        workflow = (root / ".github" / "workflows" /
                    "gis-definition-code-deploy.yml").read_text(encoding="utf-8")
        self.assertIn('MIGRATION = "0045_gis_survey_soft_delete"', command)
        self.assertIn('DEPENDENCY = "0044_gis_survey_lineage"', command)
        self.assertIn("Explicit --apply required", command)
        self.assertIn("deploy_gis_survey_lineage --apply", workflow)
        self.assertIn("trap on_exit EXIT", workflow)

    def test_connector_contract_documents_deployed_wire_boundaries(self):
        root = Path(__file__).parents[2]
        canonical_path = root / "docs" / "gis-survey-lineage-contract-v1.md"
        architecture_path = (root / "docs" / "architecture" /
                             "gis-survey-lineage-contract-v1.md")
        contract_bytes = canonical_path.read_bytes()
        self.assertEqual(contract_bytes, architecture_path.read_bytes())
        contract = contract_bytes.decode("utf-8")
        for marker in (
            "4c5fc553339bdf429b8ec5c6d656a414be484f6d",
            '"presigned_url"',
            '"object_key"',
            "The method is always `PUT`",
            "application/vnd.ms-excel",
            "HTTP 200 with an empty response body",
            '"survey_source_object_invalid"',
            "import of 22 mixed EPSG:4326/EPSG:5186 points",
            '"protocol": "survey_link_v1"',
            '"protocol":"survey_link_changeset_v1"',
            "at most 5,000 rows ordered",
            "Point-level values override request-level",
            "Client-supplied versus server-generated point values",
            "GET /gis/projects/{project_id}/api/survey-sources/{source_id}/",
            "DELETE /gis/projects/{project_id}/api/survey-sources/{source_id}/",
            '"cleanup_pending":false',
            "mode=source_only",
            "survey_source_delete_failed",
            "survey_point_delete_failed",
            "feature/geometry first, link second",
            "preview token or revision lock",
            "Reapply has no",
            "server does not remap links",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, contract)

    def test_connector_contract_markers_match_server_implementation(self):
        root = Path(__file__).parents[2]
        views = (root / "geoflow_ops" / "gis" / "survey_views.py").read_text(encoding="utf-8")
        sources = (root / "geoflow_ops" / "gis" / "survey_sources.py").read_text(encoding="utf-8")
        links = (root / "geoflow_ops" / "gis" / "survey_links.py").read_text(encoding="utf-8")
        reapply = (root / "geoflow_ops" / "gis" / "survey_reapply.py").read_text(encoding="utf-8")
        self.assertIn("expires_in=900", views)
        self.assertIn('"object_key": key, **signed', views)
        self.assertIn("LIMIT 5000", views)
        self.assertIn('"points": points', views)
        self.assertIn('"protocol": "survey_link_changeset_v1"', links)
        self.assertIn('set(raw) - {"action", "id", "link_status", "vertex_index", "link_role"}', links)
        self.assertIn('"counts": counts, "items": items', reapply)
        self.assertIn('"applied": len(events), "skipped": skipped', reapply)
        self.assertNotIn("working_crs", sources)

    def test_production_upload_smoke_checks_deferred_fk_before_rollback(self):
        root = Path(__file__).parents[2]
        command = (root / "control" / "management" / "commands" /
                   "smoke_gis_survey_source_upload.py").read_text(encoding="utf-8")
        self.assertIn("Explicit --apply required", command)
        self.assertIn('method="PUT"', command)
        self.assertIn("range(1, 23)", command)
        self.assertIn('cursor.execute("SET CONSTRAINTS ALL IMMEDIATE")', command)
        self.assertIn('"survey_date": "2026-10-05"', command)
        self.assertIn('"source_crs": "EPSG:5186"', command)
        self.assertIn('"DELETE"', command)
        self.assertIn("survey_upload_smoke_delete_precheck", command)
        self.assertIn("transaction.set_rollback(True", command)
        self.assertIn("delete_object", command)
        self.assertNotIn("presigned_url={", command)
        self.assertNotIn("object_key={", command)

    def test_survey_import_uses_changeset_receipt_lifecycle(self):
        root = Path(__file__).parents[2]
        sources = (root / "geoflow_ops" / "gis" / "survey_sources.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("_reserve_receipt(", sources)
        self.assertIn("_complete_receipt(", sources)
        self.assertLess(sources.index("_reserve_receipt("), sources.index("_insert_change_log("))

    def test_survey_source_and_point_delete_are_soft_audited_and_project_scoped(self):
        root = Path(__file__).parents[2]
        sources = (root / "geoflow_ops" / "gis" / "survey_sources.py").read_text(
            encoding="utf-8"
        )
        views = (root / "geoflow_ops" / "gis" / "survey_views.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("def survey_source_delete_precheck(", sources)
        self.assertIn("def delete_survey_source(", sources)
        self.assertIn("def delete_survey_points(", sources)
        self.assertIn("def survey_points_delete_precheck(", sources)
        self.assertIn('action="delete"', sources)
        self.assertIn('get_s3_client().delete_object', sources)
        self.assertIn('"cleanup_pending"', sources)
        self.assertIn("deleted_at IS NULL", sources)
        self.assertIn('@require_http_methods(["GET", "DELETE"])', views)
        self.assertIn('"source_only"', views)
        self.assertIn("project_survey_points_bulk_delete_api", views)
        self.assertIn('database_error="survey_source_delete_failed"', views)
        self.assertIn('database_error="survey_point_delete_failed"', views)

    def test_deleted_survey_points_are_excluded_from_reads_packages_and_reapply(self):
        root = Path(__file__).parents[2]
        for relative in (
            "geoflow_ops/gis/survey_views.py",
            "geoflow_ops/gis/survey_reapply.py",
            "geoflow_ops/gis/gpkg.py",
            "geoflow_ops/gis/gpkg_snapshot_v2.py",
            "geoflow_ops/gis/views.py",
            "geoflow_ops/gis/realtime_views.py",
        ):
            text = (root / relative).read_text(encoding="utf-8")
            with self.subTest(relative=relative):
                self.assertIn("deleted_at IS NULL", text)

    def test_survey_database_errors_are_logged_without_contract_change(self):
        root = Path(__file__).parents[2]
        views = (root / "geoflow_ops" / "gis" / "survey_views.py").read_text(
            encoding="utf-8"
        )
        self.assertIn('logger.exception("Survey database operation failed")', views)
        self.assertIn('database_error="survey_failed"', views)
        self.assertIn('{"ok": False, "error": database_error}', views)
