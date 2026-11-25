"""Real GEOS/GDAL fixtures; all provider/storage/secret calls are isolated fakes."""

import hashlib
import io
import json
from contextlib import contextmanager
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import MagicMock, patch
from uuid import uuid4

from botocore.exceptions import ClientError
from django.contrib.gis.geos import Point
from django.core.exceptions import PermissionDenied
from django.http import Http404
from django.test import RequestFactory, override_settings

from control import test_gis_references as base

# Reuse the isolated settings, not the production settings module.
from control.services import gis_reference_files as files
from control.services import gis_reference_lookup as engine
from control.services import gis_reference_vworld as vworld
from control.services.gis_references import ReferenceError
from geoflow_ops.gis import spatial_reference_views as project_views


def feature(item_id="one", value="123-1", bounds=(-0.001, -0.001, 0.001, 0.001)):
    a, b, c, d = bounds
    return {
        "type": "Feature",
        "id": item_id,
        "properties": {"pnu": "1234567890123456789", "jibun": value},
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[a, b], [c, b], [c, d], [a, d], [a, b]]],
        },
    }


class CredentialTests(TestCase):
    def test_process_cache_is_version_pinned_and_rotation_reads_new_version(self):
        vworld._version_key.cache_clear()
        self.addCleanup(vworld._version_key.cache_clear)
        cur = MagicMock()
        cur.fetchone.side_effect = [
            ("table",),
            ("v1", "https://geoflow.co.kr"),
            ("table",),
            ("v1", "https://geoflow.co.kr"),
            ("table",),
            ("v2", "https://geoflow.co.kr"),
        ]
        with patch.object(vworld, "secret_client") as client:
            client.return_value.get_secret_value.return_value = {
                "SecretString": json.dumps(
                    {"api_key": "test-only-credential-1234567890"}
                )
            }
            vworld.credential(cur)
            vworld.credential(cur)
            vworld.credential(cur)
            self.assertEqual(client.return_value.get_secret_value.call_count, 2)
            self.assertEqual(
                client.return_value.get_secret_value.call_args.kwargs["VersionId"], "v2"
            )

    def test_new_key_is_pinned_and_never_written_to_database(self):
        cur, client = MagicMock(), MagicMock()
        cur.fetchone.side_effect = [("table",), None]
        client.create_secret.side_effect = lambda **kw: {
            "VersionId": kw["ClientRequestToken"]
        }
        result = vworld.save_credential(
            cur,
            {
                "api_key": "test-only-credential-1234567890",
                "domain": "https://geoflow.co.kr",
                "revision": 0,
            },
            uuid4(),
            client,
        )
        self.assertEqual(result["revision"], 1)
        self.assertEqual(
            client.create_secret.call_args.kwargs["Name"], vworld.SECRET_ID
        )
        self.assertNotIn("test-only-credential", repr(cur.execute.call_args_list))
        self.assertNotIn("api_key", result)

    def test_rotation_uses_fixed_secret_and_explicit_version(self):
        cur, client = MagicMock(), MagicMock()
        cur.fetchone.side_effect = [("table",), (2,)]
        client.create_secret.side_effect = ClientError(
            {"Error": {"Code": "ResourceExistsException"}}, "CreateSecret"
        )
        client.put_secret_value.side_effect = lambda **kw: {
            "VersionId": kw["ClientRequestToken"]
        }
        vworld.save_credential(
            cur,
            {
                "api_key": "test-only-credential-1234567890",
                "domain": "https://geoflow.co.kr",
                "revision": 2,
            },
            uuid4(),
            client,
        )
        self.assertEqual(
            client.put_secret_value.call_args.kwargs["SecretId"], vworld.SECRET_ID
        )
        cur.fetchone.side_effect = [
            ("table",),
            ("previous-version", "https://geoflow.co.kr"),
        ]
        client.get_secret_value.return_value = {
            "SecretString": json.dumps({"api_key": "test-only-credential-1234567890"})
        }
        vworld.credential(cur, client)
        self.assertEqual(
            client.get_secret_value.call_args.kwargs["VersionId"], "previous-version"
        )

    def test_existing_runtime_key_needs_no_new_aws_permission(self):
        cur, client = MagicMock(), MagicMock()
        cur.fetchone.side_effect = [("table",), None]
        with override_settings(VWORLD_API_KEY="test-only-credential-1234567890"):
            self.assertEqual(
                vworld.credential(cur, client)[0], "test-only-credential-1234567890"
            )
        client.get_secret_value.assert_not_called()

    def test_conflict_and_invalid_domain_precede_secret_mutation(self):
        cur, client = MagicMock(), MagicMock()
        cur.fetchone.side_effect = [("table",), (3,)]
        with self.assertRaises(ReferenceError):
            vworld.save_credential(
                cur,
                {
                    "api_key": "test-only-credential-1234567890",
                    "domain": "https://geoflow.co.kr",
                    "revision": 2,
                },
                uuid4(),
                client,
            )
        client.create_secret.assert_not_called()
        for domain in (
            "https://user:pass@geoflow.co.kr",
            "https://geoflow.co.kr/?key=secret",
            "http://geoflow.co.kr",
        ):
            with self.assertRaises(ReferenceError):
                vworld.validate_domain(domain)

    def test_sdk_errors_do_not_return_key_or_provider_payload(self):
        cur, client = MagicMock(), MagicMock()
        cur.fetchone.side_effect = [("table",), None]
        client.create_secret.side_effect = ClientError(
            {"Error": {"Code": "AccessDenied", "Message": "private-api-key"}},
            "CreateSecret",
        )
        with self.assertRaises(ReferenceError) as caught:
            vworld.save_credential(
                cur,
                {
                    "api_key": "test-only-credential-1234567890",
                    "domain": "https://geoflow.co.kr",
                    "revision": 0,
                },
                uuid4(),
                client,
            )
        self.assertNotIn("private-api-key", str(caught.exception))
        self.assertNotIn("test-only-credential", repr(cur.execute.call_args_list))


class ProviderTests(TestCase):
    def response(self, total=1, found=None):
        return json.dumps(
            {
                "response": {
                    "status": "OK",
                    "record": {"total": str(total)},
                    "result": {
                        "featureCollection": {
                            "features": [feature()] if found is None else found
                        }
                    },
                }
            }
        ).encode()

    def test_fixed_endpoint_domain_and_parameter_encoding(self):
        reader = MagicMock(return_value=self.response())
        result = vworld.features(
            "parcel",
            Point(0, 0, srid=4326),
            "test-key",
            "https://geoflow.co.kr",
            reader,
        )
        self.assertEqual(result[0]["properties"]["jibun"], "123-1")
        url = reader.call_args.args[0]
        self.assertTrue(url.startswith(vworld.ENDPOINT + "?"))
        self.assertIn("LP_PA_CBND_BUBUN", url)
        self.assertIn("POINT", url)
        self.assertEqual(reader.call_args.kwargs["domain"], "https://geoflow.co.kr")

    def test_error_and_truncation_never_become_partial_ready(self):
        for value in (
            self.response(101),
            self.response(2),
            b"{}",
            b"<html>error</html>",
            b'{"response":{"status":"ERROR","message":"private-key"}}',
        ):
            with self.assertRaises(ReferenceError) as caught:
                vworld.features(
                    "parcel",
                    Point(0, 0, srid=4326),
                    "test-key",
                    "https://geoflow.co.kr",
                    lambda *a, value=value, **k: value,
                )
            self.assertNotIn("private-key", str(caught.exception))

    def test_tile_parameters_precede_network_and_invalid_body_is_rejected(self):
        reader = MagicMock(return_value=b"not-a-tile")
        with self.assertRaises(ReferenceError):
            vworld.tile("bad", 1, 0, 0, "key", "https://geoflow.co.kr", reader)
        reader.assert_not_called()
        with self.assertRaises(ReferenceError):
            vworld.tile("Base", 1, 0, 0, "key", "https://geoflow.co.kr", reader)


class GeometrySelectionTests(TestCase):
    def test_pipe_crossing_parcels_returns_both_actual_jibun_values(self):
        line = engine.geometry(
            {"type": "LineString", "coordinates": [[-0.001, 0], [0.001, 0]]}
        )
        result = engine.select(
            line,
            [
                feature("a", "100", (-0.002, -0.001, 0, 0.001)),
                feature("b", "101", (0, -0.001, 0.002, 0.001)),
            ],
            {"selection": "all", "fields": ["jibun"]},
        )
        self.assertEqual(result["values"]["jibun"], ["100", "101"])

    def test_shared_boundary_is_ambiguous_and_all_includes_both(self):
        candidates = [
            feature("a", bounds=(-0.001, -0.001, 0, 0.001)),
            feature("b", value="124", bounds=(0, -0.001, 0.001, 0.001)),
        ]
        target = Point(0, 0, srid=4326)
        result = engine.select(target, candidates, {"fields": ["jibun"]})
        self.assertEqual(result["status"], "AMBIGUOUS")
        self.assertEqual(result["values"], {"jibun": []})
        result = engine.select(
            target, candidates, {"fields": ["jibun"], "selection": "all"}
        )
        self.assertEqual(result["values"]["jibun"], ["123-1", "124"])
        self.assertFalse(result["written"])

    def test_selected_id_must_be_an_actual_intersection(self):
        with self.assertRaises(ReferenceError):
            engine.select(
                Point(0, 0, srid=4326),
                [feature()],
                {"selection": "selected", "chosen_id": "other"},
            )
        value = engine.select(
            Point(0, 0, srid=4326),
            [feature()],
            {"selection": "selected", "chosen_id": "one", "fields": ["pnu"]},
        )
        self.assertEqual(value["status"], "READY")

    def test_bbox_false_positives_are_removed_and_no_match_has_no_values(self):
        value = engine.select(
            Point(0, 0, srid=4326),
            [feature(bounds=(0.002, 0.002, 0.003, 0.003))],
            {"fields": ["jibun"]},
        )
        self.assertEqual(value["status"], "NO_MATCH")
        self.assertEqual(value["values"]["jibun"], [])

    def test_geographic_bounds_invalid_crs_and_large_requests_fail(self):
        for point, crs in (([999, 999], "EPSG:4326"), ([0, 0], "unknown")):
            with self.assertRaises(ReferenceError):
                engine.geometry({"type": "Point", "coordinates": point}, crs)
        with self.assertRaises(ReferenceError):
            engine.geometry({"type": "LineString", "coordinates": [[0, 0], [1, 1]]})
        p = engine.geometry(
            {"type": "Point", "coordinates": [237000, 420000]}, "EPSG:5186"
        )
        self.assertEqual(p.srid, 4326)


class FileLookupTests(TestCase):
    def setUp(self):
        self.temp = TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.item = {"version": {"declared_crs": "EPSG:4326"}}

        @contextmanager
        def local(_):
            yield self.root

        self.mock = patch.object(files, "local_original", local)
        self.mock.start()
        self.addCleanup(self.mock.stop)

    def test_geojson_field_discovery_and_exact_polygon_lookup(self):
        (self.root / "sheet.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "features": [feature()]})
        )
        layers = engine.inspect_file(self.item)
        self.assertIn("jibun", layers[0]["fields"])
        result = engine.select(
            Point(0, 0, srid=4326),
            engine.file_features(
                self.item, Point(0, 0, srid=4326), {"layer": layers[0]["name"]}
            ),
            {"fields": ["jibun"]},
        )
        self.assertEqual(result["values"]["jibun"], ["123-1"])

    def test_coordinate_csv_requires_explicit_axes_and_does_not_guess(self):
        (self.root / "points.csv").write_text(
            "번호,동좌표,북좌표\nP1,127,36\nP2,128,37\n", encoding="utf-8-sig"
        )
        layers = engine.inspect_file(self.item)
        self.assertEqual(layers[0]["kind"], "xy")
        with self.assertRaises(ReferenceError):
            list(
                engine.file_features(
                    self.item, Point(127, 36, srid=4326), {"layer": "points.csv"}
                )
            )
        records = list(
            engine.file_features(
                self.item,
                Point(127, 36, srid=4326),
                {
                    "layer": "points.csv",
                    "x_field": "동좌표",
                    "y_field": "북좌표",
                    "reference_crs": "EPSG:4326",
                },
            )
        )
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["properties"]["번호"], "P1")

    def test_excel_coordinate_list_keeps_identifiers_and_uses_declared_crs(self):
        from openpyxl import Workbook

        book = Workbook()
        sheet = book.active
        sheet.append(["번호", "X", "Y"])
        sheet.append(["001", 127, 36])
        book.save(self.root / "points.xlsx")
        book.close()
        layers = engine.inspect_file(self.item)
        self.assertEqual(layers[0]["fields"], ["번호", "X", "Y"])
        records = list(
            engine.file_features(
                self.item,
                Point(127, 36, srid=4326),
                {"layer": "points.xlsx", "x_field": "X", "y_field": "Y"},
            )
        )
        self.assertEqual(records[0]["properties"]["번호"], "001")

    def test_pdf_is_preserved_as_document_not_invented_geometry(self):
        (self.root / "result.pdf").write_bytes(b"%PDF")
        with self.assertRaises(ReferenceError):
            engine.inspect_file(self.item)

    def test_vrt_content_cannot_be_opened_under_geojson_extension(self):
        (self.root / "disguised.geojson").write_text(
            '<OGRVRTDataSource><OGRVRTLayer name="bad"><SrcDataSource>/nonexistent/reference.csv</SrcDataSource></OGRVRTLayer></OGRVRTDataSource>'
        )
        with self.assertRaises(ReferenceError):
            engine.inspect_file(self.item)


class TemporaryOriginalTests(TestCase):
    def test_zip_is_safely_unpacked_only_for_operation_and_then_removed(self):
        raw = base.archive(
            [
                (
                    "index/sheet.geojson",
                    json.dumps({"type": "FeatureCollection", "features": [feature()]}),
                )
            ]
        )
        body = io.BytesIO(raw)
        version = {
            "filename": "reference.zip",
            "object_key": "central/gis/references/test/original.zip",
            "size_bytes": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
        }
        with (
            patch(
                "geoflow_ops.services.s3_service.get_bucket_name",
                return_value="test-bucket",
            ),
            patch("geoflow_ops.services.s3_service.get_s3_client") as client,
        ):
            client.return_value.get_object.return_value = {"Body": body}
            with files.local_original(version) as root:
                saved = root
                self.assertTrue((root / "unpacked/index/sheet.geojson").is_file())
                self.assertEqual(len(engine.vectors(root)), 1)
            self.assertFalse(saved.exists())
            self.assertTrue(body.closed)

    def test_wrong_hash_is_not_used_and_stream_is_closed(self):
        body = io.BytesIO(b"abc")
        with (
            patch(
                "geoflow_ops.services.s3_service.get_bucket_name",
                return_value="test-bucket",
            ),
            patch("geoflow_ops.services.s3_service.get_s3_client") as client,
        ):
            client.return_value.get_object.return_value = {"Body": body}
            with (
                self.assertRaises(ReferenceError),
                files.local_original(
                    {
                        "filename": "a.csv",
                        "object_key": "key",
                        "size_bytes": 3,
                        "sha256": "0" * 64,
                    }
                ),
            ):
                self.fail("unverified original must never be yielded")
            self.assertTrue(body.closed)


class ProjectBoundaryTests(TestCase):
    def request(self, method="post", body=None):
        request = (
            RequestFactory().get("/")
            if method == "get"
            else RequestFactory().post(
                "/", data=json.dumps(body or {}), content_type="application/json"
            )
        )
        request.user = SimpleNamespace(is_authenticated=True)
        request._dont_enforce_csrf_checks = True
        return request

    def test_denied_project_never_queries_provider_or_file(self):
        with (
            patch.object(project_views, "_context", side_effect=PermissionDenied),
            patch.object(engine, "lookup") as lookup,
        ):
            with self.assertRaises(PermissionDenied):
                project_views.project_reference_lookup(self.request(), uuid4())
            lookup.assert_not_called()

    def test_server_project_geometry_overrides_client_supplied_geometry(self):
        actual = {"type": "Point", "coordinates": [127, 36]}
        request = self.request(
            body={"geometry": {"type": "Point", "coordinates": [0, 0]}}
        )
        with (
            patch.object(
                project_views,
                "_context",
                return_value=("tenant", SimpleNamespace(id=uuid4()), {}),
            ),
            patch.object(project_views, "_target", return_value=actual),
            patch.object(project_views, "connections", {"default": MagicMock()}),
            patch.object(engine, "lookup", return_value={"status": "READY"}) as lookup,
        ):
            self.assertEqual(
                project_views.project_reference_lookup(request, uuid4()).status_code,
                200,
            )
            self.assertEqual(lookup.call_args.args[1]["geometry"], actual)

    def test_tile_authentication_precedes_credentials_and_invalid_tile_never_fetches(
        self,
    ):
        with (
            patch.object(project_views, "_context", return_value=None),
            patch.object(vworld, "credential") as credential,
        ):
            with self.assertRaises(Http404):
                project_views.project_reference_tile(
                    self.request("get"), uuid4(), "Base", 20, 0, 0
                )
            credential.assert_not_called()

    def test_background_config_has_no_raw_key(self):
        root = Path(__file__).resolve().parents[1]
        js = (root / "geoflow_ops/static/geoflow_ops/js/gis-project-map.js").read_text()
        self.assertNotIn("vworldConfig.key", js)
        self.assertIn("vworldConfig.tile_url", js)
