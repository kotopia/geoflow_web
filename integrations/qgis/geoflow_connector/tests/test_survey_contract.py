"""Offline request tests; these do not establish operational API compatibility."""
import unittest
import tempfile
import io
import urllib.error
from pathlib import Path
from unittest.mock import Mock
from unittest.mock import patch

from api.survey import (SurveyApi, survey_mime_type,
                        validate_presign_response, validate_import_response,
                        presign_response_shape, presign_response_diagnostic,
                        survey_import_request_shape,
                        SURVEY_POINT_REQUEST_KEYS,
                        SURVEY_POINT_RESPONSE_KEYS)
from api.client import GeoFlowHttpClient, GeoFlowDetailedApiError


PROJECT = "10000000-0000-4000-8000-000000000001"
SOURCE = "30000000-0000-4000-8000-000000000002"
MAPPING = "40000000-0000-4000-8000-000000000003"
SURVEY = "50000000-0000-4000-8000-000000000001"
TARGET = "60000000-0000-4000-8000-000000000001"


class SurveyContractTests(unittest.TestCase):
    def setUp(self):
        self.client = Mock(base_url="https://example.invalid/extra/path")
        self.client.post_json_detailed.return_value = {"ok": True}
        self.api = SurveyApi(self.client, PROJECT)
        self.root = f"https://example.invalid/gis/projects/{PROJECT}/api/"

    def test_project_paths_and_encoded_filters(self):
        self.api.sources(include_inactive=True)
        self.client.get_json.assert_called_with(self.root + "survey-sources/?include_inactive=1")
        self.api.points(source_id=SOURCE)
        self.client.get_json.assert_called_with(self.root + "survey-points/?source_id=" + SOURCE)
    def test_source_detail_and_delete_paths(self):
        self.api.source(SOURCE)
        self.client.get_json.assert_called_with(self.root + "survey-sources/" + SOURCE + "/")
        self.api.delete_source(SOURCE)
        self.client.delete_json_detailed.assert_called_with(
            self.root + "survey-sources/" + SOURCE + "/?mode=source_only"
        )
        self.api.points(source_id=None)
        self.client.get_json.assert_called_with(self.root + "survey-points/")

    def test_presign_and_import_do_not_infer_upload_response(self):
        response = {"unspecified_response_envelope": {}}
        self.client.post_json.return_value = response
        self.client.post_json_detailed.return_value = response
        self.assertIs(self.api.presign(source_id=SOURCE,
                      original_file_name="측량.csv", mime_type="text/csv"), response)
        self.client.post_json.assert_called_with(self.root + "survey-sources/", {
            "action": "presign", "id": SOURCE,
            "original_file_name": "측량.csv", "mime_type": "text/csv"})
        payload = {"id": SOURCE, "source_type": "TOTAL", "source_crs": "EPSG:5186",
                   "original_file_name": "측량.csv", "points": [
                       {"source_row_id": "001", "raw_x": 200000.12, "raw_y": 500000.34}]}
        self.assertIs(self.api.import_source(payload), response)
        self.client.post_json_detailed.assert_called_with(self.root + "survey-sources/", payload)

    def test_deployed_presign_and_import_response_contract(self):
        signed = validate_presign_response({
            "ok": True, "id": SOURCE,
            "presigned_url": "https://storage.example/upload",
            "object_key": "gis-survey/t/p/source.csv",
            "headers": {"Content-Type": "text/csv",
                        "x-amz-server-side-encryption": "AES256"},
        })
        self.assertEqual(signed["method"], "PUT")
        actual_diagnostic = presign_response_diagnostic({
            "ok": True, "id": SOURCE, "presigned_url": "https://storage.example/upload",
            "object_key": "key", "headers": {"Content-Type": "text/csv"}})
        self.assertFalse(actual_diagnostic["method_exists"])
        self.assertEqual(actual_diagnostic["method_repr"], "None")
        self.assertEqual(actual_diagnostic["method_normalized"], "PUT")
        self.assertEqual(actual_diagnostic["method_source"], "implicit_put_contract")
        shape = presign_response_shape({"presigned_url": "https://secret", "headers": {"x": "secret"}})
        self.assertEqual(shape, {"presigned_url": "str", "headers": {"x": "str"}})
        self.assertNotIn("secret", str(shape))
        for raw_method in ("PUT", "put", "Put", " Put "):
            normalized = validate_presign_response({
                "ok": True,
                "presigned_url": "https://storage.example/upload",
                "object_key": "key", "method": raw_method, "headers": {}})
            self.assertEqual(normalized["method"], "PUT")
        diagnostic = presign_response_diagnostic({
            "presigned_url": "https://storage.example/secret", "object_key": "secret-key",
            "method": " put ", "headers": {"Content-Type": "secret-value"}})
        self.assertTrue(diagnostic["method_exists"])
        self.assertEqual(diagnostic["method_repr"], "' put '")
        self.assertEqual(diagnostic["method_type"], "str")
        self.assertEqual(diagnostic["method_normalized"], "PUT")
        self.assertEqual(diagnostic["header_keys"], ["Content-Type"])
        self.assertNotIn("secret-value", str(diagnostic))
        self.assertEqual(survey_mime_type("a.csv"), "text/csv")
        self.assertEqual(survey_mime_type("a.xls"), "application/vnd.ms-excel")
        self.assertIn("spreadsheetml", survey_mime_type("a.xlsx"))
        response_point = {
            "id": SURVEY, "source_row_id": "P1", "survey_no": "261017-001",
            "type": "GNSS", "raw_x": 1.0, "raw_y": 2.0, "raw_z": 3.0,
            "x": 1.0, "y": 2.0, "z": 3.0,
            "longitude": 127.0, "latitude": 36.0,
        }
        summary = validate_import_response({
            "source_id": SOURCE, "source_group_id": PROJECT, "version": 1,
            "created": 22, "updated": 0, "points": [response_point],
        }, SOURCE)
        self.assertEqual((summary["created"], summary["updated"]), (22, 0))
        self.assertEqual(summary["points"][0], response_point)
        for field in ("survey_no", "type", "x", "y", "z"):
            self.assertNotIn(field, SURVEY_POINT_REQUEST_KEYS)
            self.assertIn(field, SURVEY_POINT_RESPONSE_KEYS)
        for invalid in ({}, {"ok": True, "presigned_url": "http://unsafe", "object_key": "x",
                            "method": "PUT", "headers": {}},
                        {"ok": True, "presigned_url": "https://x", "object_key": "x",
                         "method": "POST", "headers": {}}):
            with self.assertRaises(ValueError):
                validate_presign_response(invalid)
        with self.assertRaises(ValueError):
            validate_import_response({"source_id": SOURCE, "created": 22}, SOURCE)
        request_shape = survey_import_request_shape({
            "source_type": "TOTAL", "survey_type": "TOTAL_STATION",
            "source_crs": "EPSG:5186", "target_crs": "EPSG:5186",
            "original_file_key": "secret", "points": [
                {"source_row_id": "P1", "raw_x": 1, "raw_y": 2, "raw_z": 3}]})
        self.assertEqual(request_shape["point_count"], 1)
        self.assertEqual(request_shape["survey_type"], "TOTAL_STATION")
        self.assertEqual(request_shape["target_crs"], "EPSG:5186")
        self.assertEqual(request_shape["point_keys"], ["raw_x", "raw_y", "raw_z", "source_row_id"])
        self.assertNotIn("secret", str(request_shape))

    def test_survey_source_put_uses_full_file_and_response_headers(self):
        client = GeoFlowHttpClient("https://example.invalid")
        response = Mock(status=200)
        response.__enter__ = Mock(return_value=response); response.__exit__ = Mock(return_value=False)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "source.csv"; path.write_bytes(b"id,x,y\nP1,1,2\n")
            with patch("api.client.urllib.request.urlopen", return_value=response) as send:
                client.put_presigned_source_file(
                    "https://storage.example/upload", str(path), {"x-amz-server-side-encryption": "AES256"}, "PUT")
        request = send.call_args.args[0]
        self.assertEqual(request.get_method(), "PUT")
        self.assertEqual(request.data, b"id,x,y\nP1,1,2\n")
        self.assertEqual(request.get_header("X-amz-server-side-encryption"), "AES256")

    def test_detailed_post_preserves_safe_server_error(self):
        client = GeoFlowHttpClient("https://example.invalid")
        client._cookie_value = Mock(return_value="csrf")
        body = (b'{"code":"survey_failed","message":"import failed",'
                b'"detail":"tenant operation unavailable","field_errors":{"points":"invalid"},'
                b'"object_key":"secret"}')
        failure = urllib.error.HTTPError(
            "https://example.invalid/api", 503, "failed", {}, io.BytesIO(body))
        client.opener.open = Mock(side_effect=failure)
        with self.assertRaises(GeoFlowDetailedApiError) as raised:
            client.post_json_detailed("/api", {"points": []})
        error = raised.exception
        self.assertEqual(error.http_status, 503)
        self.assertEqual(error.code, "survey_failed")
        self.assertEqual(error.detail, "tenant operation unavailable")
        self.assertEqual(error.field_errors, {"points": "invalid"})
        self.assertIn("object_key", error.response_keys)
        self.assertNotIn("secret", str(error.__dict__))

    def test_detailed_post_reads_nested_error_without_sensitive_values(self):
        client = GeoFlowHttpClient("https://example.invalid")
        client._cookie_value = Mock(return_value="csrf")
        body = (b'{"error":{"code":"survey_failed","message":"worker failed",'
                b'"detail":"conversion failed","field_errors":{"points":"invalid"}},'
                b'"headers":{"Authorization":"secret-token"}}')
        failure = urllib.error.HTTPError(
            "https://example.invalid/api", 503, "failed", {}, io.BytesIO(body))
        client.opener.open = Mock(side_effect=failure)
        with self.assertRaises(GeoFlowDetailedApiError) as raised:
            client.post_json_detailed("/api", {"points": []})
        error = raised.exception
        self.assertEqual(error.code, "survey_failed")
        self.assertEqual(error.server_message, "worker failed")
        self.assertEqual(error.detail, "conversion failed")
        self.assertEqual(error.field_errors, {"points": "invalid"})
        self.assertNotIn("secret-token", str(error.__dict__))

    def test_delete_has_no_request_body(self):
        client = GeoFlowHttpClient("https://example.invalid")
        client._cookie_value = Mock(return_value="csrf")
        response = Mock(status=200)
        response.read.return_value = b'{}'
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        client.opener.open = Mock(return_value=response)
        client.delete_json("/api/source/")
        request = client.opener.open.call_args.args[0]
        self.assertEqual(request.get_method(), "DELETE")
        self.assertIsNone(request.data)
        self.assertIsNone(request.get_header("Content-length"))







if __name__ == "__main__":
    unittest.main()
