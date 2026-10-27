"""Survey adapter with separate deployed request and response contracts.

Responses are returned unchanged by request methods. The Survey import workflow
validates the deployed presign/import response contract before using it.
No fallback endpoints, conflict repair, automatic retries, or CRS conversions.
"""
from __future__ import annotations

from urllib.parse import urlencode, urlsplit, urlunsplit
from uuid import UUID
from pathlib import Path
from collections.abc import Mapping


SURVEY_POINT_REQUEST_KEYS = frozenset({
    "id", "source_row_id", "raw_x", "raw_y", "raw_z", "raw_crs",
    "raw_code", "raw_geoid_model", "longitude", "latitude", "raw_data",
    "worker_id", "survey_date", "name", "code", "solution_info", "pdop",
    "antenna_height",
})

SURVEY_POINT_RESPONSE_KEYS = SURVEY_POINT_REQUEST_KEYS | frozenset({
    "source_id", "project_id", "survey_no", "type", "x", "y", "z",
    "survey_code", "surveyed_at", "filter", "description", "raw_geom",
    "geom", "created_at", "updated_at",
})


def _uuid(value):
    return str(UUID(str(value)))


def survey_mime_type(path):
    suffix = Path(path).suffix.lower()
    values = {
        ".csv": "text/csv",
        ".xls": "application/vnd.ms-excel",
        ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    }
    if suffix not in values:
        raise ValueError("CSV, XLS 또는 XLSX 파일만 업로드할 수 있습니다.")
    return values[suffix]


def presign_response_shape(value):
    """Return field names and value types while redacting all response values."""
    if isinstance(value, dict):
        return {str(key): presign_response_shape(child) for key, child in value.items()}
    if isinstance(value, list):
        return {"type": "list", "length": len(value),
                "items": presign_response_shape(value[0]) if value else "empty"}
    return type(value).__name__


def presign_response_diagnostic(payload):
    """Expose only non-secret validation facts for the QGIS debug log."""
    if not isinstance(payload, dict):
        return {"response_type": type(payload).__name__}
    keys = sorted(str(name) for name in payload.keys())
    url = payload.get("presigned_url")
    key = payload.get("object_key")
    method = payload.get("method")
    headers = payload.get("headers")
    normalized = ("PUT" if "method" not in payload else
                  (str(method).strip().upper() if method is not None else ""))
    url_fields = sorted(str(name) for name, value in payload.items()
                        if isinstance(value, str) and value.startswith("https://"))
    object_key_fields = sorted(str(name) for name, value in payload.items()
                               if "key" in str(name).casefold()
                               and isinstance(value, str) and bool(value.strip()))
    return {
        "keys": keys,
        "method_exists": "method" in payload,
        "method_repr": repr(method),
        "method_type": type(method).__name__,
        "method_source": "response" if "method" in payload else "implicit_put_contract",
        "presigned_url": "https str" if isinstance(url, str) and url.startswith("https://")
                          else type(url).__name__,
        "object_key": "non-empty str" if isinstance(key, str) and key.strip()
                      else type(key).__name__,
        "url_field_names": url_fields,
        "object_key_field_names": object_key_fields,
        "method_normalized": normalized,
        "headers_type": type(headers).__name__,
        "header_keys": sorted(str(name) for name in headers.keys())
                       if isinstance(headers, Mapping) else [],
    }


def validate_presign_response(payload):
    """Validate the deployed Survey presign response without aliases/fallbacks."""
    if not isinstance(payload, dict):
        raise ValueError("Survey presign 응답이 JSON 객체가 아닙니다.")
    url = payload.get("presigned_url")
    # Deployed presign response names the storage result ``object_key``.
    # ``original_file_key`` belongs only to the following import request.
    key = payload.get("object_key")
    method = payload.get("method")
    headers = payload.get("headers")
    method_exists = "method" in payload
    normalized_method = ("PUT" if not method_exists else
                         (str(method).strip().upper() if method is not None else ""))
    if payload.get("ok") is not True:
        raise ValueError("Survey presign 응답의 ok 상태가 유효하지 않습니다.")
    if not isinstance(url, str) or not url.startswith("https://"):
        raise ValueError("Survey presign 응답의 presigned_url이 유효하지 않습니다.")
    if not isinstance(key, str) or not key.strip():
        raise ValueError("Survey presign 응답의 object_key가 유효하지 않습니다.")
    if method_exists and (not isinstance(method, str) or normalized_method != "PUT"):
        raise ValueError("Survey presign 응답의 method는 PUT이어야 합니다.")
    if not isinstance(headers, Mapping):
        raise ValueError("Survey presign 응답의 headers가 유효하지 않습니다.")
    return {"presigned_url": url, "object_key": key.strip(),
            "method": normalized_method, "headers": dict(headers)}


def validate_import_response(payload, expected_source_id):
    """Return stable import counters from the deployed response contract."""
    if not isinstance(payload, dict):
        raise ValueError("Survey import 응답이 JSON 객체가 아닙니다.")
    try:
        source_id = _uuid(payload.get("source_id"))
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Survey import 응답의 source_id가 유효하지 않습니다.") from None
    if source_id != _uuid(expected_source_id):
        raise ValueError("Survey import 응답의 source_id가 요청과 다릅니다.")
    created, updated = payload.get("created"), payload.get("updated")
    if (type(created) is not int or created < 0 or
            type(updated) is not int or updated < 0):
        raise ValueError("Survey import 응답의 created/updated 건수가 유효하지 않습니다.")
    points = payload.get("points", [])
    if points is None:
        points = []
    if not isinstance(points, list) or any(
            not isinstance(point, Mapping) for point in points):
        raise ValueError("Survey import 응답의 points가 유효하지 않습니다.")
    return {"source_id": source_id, "created": created, "updated": updated,
            "source_group_id": payload.get("source_group_id"),
            "version": payload.get("version"),
            "points": [dict(point) for point in points]}


def survey_import_request_shape(payload):
    """Describe an import request without logging keys, coordinates, or row IDs."""
    payload = payload if isinstance(payload, dict) else {}
    points = payload.get("points") if isinstance(payload.get("points"), list) else []
    point_keys = sorted({str(key) for point in points if isinstance(point, dict)
                         for key in point.keys()})
    return {
        "keys": sorted(str(key) for key in payload.keys()),
        "source_type": str(payload.get("source_type") or ""),
        "survey_type": str(payload.get("survey_type") or ""),
        "has_original_file_key": bool(payload.get("original_file_key")),
        "source_crs": str(payload.get("source_crs") or ""),
        "target_crs": str(payload.get("target_crs") or ""),
        "point_count": len(points),
        "point_keys": point_keys,
        "has_source_group_id": bool(payload.get("source_group_id")),
        "has_supersedes_id": bool(payload.get("supersedes_id")),
    }


class SurveyApi:
    """Use the existing authenticated HTTP session with exact project endpoints."""

    def __init__(self, client, project_id):
        self.client = client
        origin = urlsplit(client.base_url)
        if origin.scheme not in {"http", "https"} or not origin.netloc:
            raise ValueError("A server origin is required")
        # The existing client's _url strips leading slashes. Use a same-origin
        # absolute URL so a base URL path cannot relocate contract endpoints.
        self.root = urlunsplit((origin.scheme, origin.netloc,
                                f"/gis/projects/{_uuid(project_id)}/api/", "", ""))

    def _get(self, endpoint, **query):
        suffix = "?" + urlencode(query) if query else ""
        return self.client.get_json(self.root + endpoint + "/" + suffix)

    def _post(self, endpoint, payload):
        return self.client.post_json(self.root + endpoint + "/", payload)

    def sources(self, *, include_inactive=False, include_deleted=False):
        query = {}
        if include_inactive:
            query['include_inactive'] = 1
        if include_deleted:
            query['include_deleted'] = 1
        return self._get("survey-sources", **query)

    def source(self, source_id):
        """Return the delete precheck fields for one source version."""
        return self._get("survey-sources/" + _uuid(source_id))

    def delete_source(self, source_id):
        """Execute only the explicitly acknowledged Source + Point contract."""
        url = (self.root + "survey-sources/" + _uuid(source_id)
               + "/?mode=source_and_points&deletion_policy=source_and_points_soft_delete_v1")
        detailed = getattr(self.client, "delete_json_detailed", None)
        return (detailed or self.client.delete_json)(url)

    def presign(self, *, source_id, original_file_name, mime_type):
        return self._post("survey-sources", {
            "action": "presign", "id": _uuid(source_id),
            "original_file_name": original_file_name, "mime_type": mime_type,
        })

    def import_source(self, payload):
        # Accept an already contract-shaped payload; do not invent CSV/XLSX
        # mappings for operator/date/method fields absent from the contract.
        return self.client.post_json_detailed(
            self.root + "survey-sources/", payload)

    def points(self, *, source_id=None, source_state=None):
        query = {"source_id": _uuid(source_id)} if source_id is not None else {}
        if source_state is not None:
            if source_state != 'retained':
                raise ValueError('Unsupported Source state')
            query['source_state'] = source_state
        return self._get("survey-points", **query)
