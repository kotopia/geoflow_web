"""Survey actions coordinated with the existing facility sync engine."""
from copy import deepcopy
import json

from qgis.core import QgsMessageLog, Qgis

from ..api.survey import (SurveyApi,
                          survey_mime_type, validate_presign_response,
                          validate_import_response, presign_response_shape,
                          presign_response_diagnostic,
                          survey_import_request_shape,
                          SURVEY_POINT_REQUEST_KEYS)


def _redact_survey_diagnostic(value, secrets):
    """Remove request-scoped storage/auth values from a diagnostic payload."""
    if isinstance(value, dict):
        return {key: _redact_survey_diagnostic(child, secrets)
                for key, child in value.items()}
    if isinstance(value, list):
        return [_redact_survey_diagnostic(child, secrets) for child in value]
    if not isinstance(value, str):
        return value
    result = value
    for secret in secrets:
        if secret:
            result = result.replace(secret, "[redacted]")
    return result


class SurveyController:
    def __init__(self, plugin):
        self.plugin = plugin

    def context(self, write=False):
        state = self.plugin.integration_state()
        if not state.get("ready") or (write and not state.get("can_write")):
            raise RuntimeError("활성 프로젝트와 해당 GIS 권한이 필요합니다.")
        return self.plugin.active_context, SurveyApi(self.plugin.active_client, state["project_id"])

    def clean(self):
        if self.plugin._sync_in_progress:
            raise RuntimeError("기존 동기화 완료 후 실행하세요.")
        for layer in self.plugin._managed_layers():
            if layer.isModified():
                raise RuntimeError("QGIS 편집을 먼저 저장하거나 취소하세요. Survey 작업은 미저장 편집을 자동 저장하지 않습니다.")
        work = getattr(self.plugin, "work", None)
        if work is not None and work._dirty_page() is not None:
            raise RuntimeError("열린 객체의 미저장 입력을 먼저 저장하거나 취소하세요.")

    def import_source_file(self, payload, file_path, progress=lambda _text: None):
        """Presign, upload once, then import all validated point rows."""
        if not isinstance(payload, dict) or not isinstance(payload.get("points"), list) or not payload["points"]:
            raise ValueError("검증된 Survey Point 요청이 없습니다.")
        for index, point in enumerate(payload["points"], 1):
            if not isinstance(point, dict):
                raise ValueError(f"{index}번째 Survey Point가 JSON 객체가 아닙니다.")
            unknown = set(point) - SURVEY_POINT_REQUEST_KEYS
            if unknown:
                raise ValueError("Survey Point에 허용되지 않은 key가 있습니다: " +
                                 ", ".join(sorted(str(key) for key in unknown)))
        if payload.get("survey_type") not in {"GNSS", "TOTAL_STATION"}:
            raise ValueError("survey_type은 GNSS 또는 TOTAL_STATION이어야 합니다.")
        context, api = self.context(write=True)
        self.clean()
        progress("업로드 준비 중")
        raw_presign = api.presign(
            source_id=payload["id"], original_file_name=payload["original_file_name"],
            mime_type=survey_mime_type(file_path))
        QgsMessageLog.logMessage(
            "survey_presign_response_shape=" + json.dumps(
                presign_response_shape(raw_presign), ensure_ascii=False, sort_keys=True),
            "GeoFlow", Qgis.MessageLevel.Info,
        )
        diagnostic = presign_response_diagnostic(raw_presign)
        QgsMessageLog.logMessage(
            "survey_presign_method=" + diagnostic.get("method_repr", "missing"),
            "GeoFlow", Qgis.MessageLevel.Info,
        )
        QgsMessageLog.logMessage(
            "survey_presign_validation=" + json.dumps(
                diagnostic, ensure_ascii=False, sort_keys=True, default=str),
            "GeoFlow", Qgis.MessageLevel.Info,
        )
        presign = validate_presign_response(raw_presign)
        progress("원본 파일 업로드 중")
        try:
            self.plugin.active_client.put_presigned_source_file(
                presign["presigned_url"], str(file_path), presign["headers"],
                "PUT")
        except Exception as exc:
            # Do not retry or expose/store the signed URL and object key.
            raise RuntimeError("측량 원본 파일 업로드에 실패했습니다.") from exc
        progress("Survey 생성 중")
        request = deepcopy(payload)
        # Response storage key and import request field intentionally have
        # different names in the deployed contract.
        request["original_file_key"] = presign["object_key"]
        QgsMessageLog.logMessage(
            "survey_import_request_shape=" + json.dumps(
                survey_import_request_shape(request), ensure_ascii=False,
                sort_keys=True),
            "GeoFlow", Qgis.MessageLevel.Info,
        )
        diagnostic_fields = (
            "raw_x", "raw_y", "raw_z", "latitude", "longitude",
            "antenna_height", "survey_date", "code", "raw_code",
        )
        for index, point in enumerate(request["points"][:3], 1):
            QgsMessageLog.logMessage(
                "[SURVEY_IMPORT_POINT] " + json.dumps(
                    {"index": index, **{
                        field: point[field] for field in diagnostic_fields
                        if field in point
                    }}, ensure_ascii=False, sort_keys=True, default=str),
                "GeoFlow", Qgis.MessageLevel.Info,
            )
        try:
            response = api.import_source(request)
        except Exception as exc:
            error = {
                "http_status": getattr(exc, "http_status", None),
                "code": getattr(exc, "code", ""),
                "message": getattr(exc, "server_message", "") or str(exc),
                "detail": getattr(exc, "detail", None),
                "field_errors": getattr(exc, "field_errors", None),
                "keys": getattr(exc, "response_keys", []),
            }
            secret_values = [presign.get("presigned_url"),
                             presign.get("object_key")]
            secret_values.extend(str(value) for value in
                                 presign.get("headers", {}).values())
            error = _redact_survey_diagnostic(error, secret_values)
            QgsMessageLog.logMessage(
                "survey_import_error=" + json.dumps(
                    error, ensure_ascii=False, sort_keys=True, default=str),
                "GeoFlow", Qgis.MessageLevel.Critical,
            )
            raise
        summary = validate_import_response(response, payload["id"])
        return {**summary, "response": response,
                "response_points": summary["points"],
                "local_count": len(payload["points"])}

    def refresh_imported_points(self):
        """Pull committed Survey rows through the normal server-Delta path."""
        context, _api = self.context(write=True)
        package_path = str(context.get("package_path") or "")
        if not package_path:
            return False
        self.plugin._pull_clean_snapshot_delta(
            self.plugin.active_client,
            package_path,
            context.get("manifest") or {},
        )
        return True

    @staticmethod
    def _delete_precheck(payload):
        if not isinstance(payload, dict) or not isinstance(payload.get("delete"), dict):
            raise ValueError("Source 삭제 사전 확인 응답에 delete 객체가 없습니다.")
        check = dict(payload["delete"])
        allowed = check.get("can_delete_source_only", check.get("can_delete"))
        if type(allowed) is not bool:
            raise ValueError("Source 삭제 사전 확인 응답의 can_delete가 유효하지 않습니다.")
        check["can_delete"] = allowed
        if check.get("source_only_blocked_reason") is not None:
            check["blocked_reason"] = check.get("source_only_blocked_reason")
        return check

    def source_delete_precheck(self, source_id):
        self.clean()
        _, api = self.context(write=True)
        payload = api.source(source_id)
        return payload, self._delete_precheck(payload)

    def delete_source(self, source_id):
        """Delete Source metadata/file only; Survey points and GIS features must survive."""
        self.clean()
        _, api = self.context(write=True)
        latest = self._delete_precheck(api.source(source_id))
        source_only_allowed = {
            "survey_source_in_use",
        }
        reason = str(latest.get("blocked_reason") or "")
        if not latest["can_delete"] and reason not in source_only_allowed:
            raise ValueError("Source 상태가 변경되어 삭제할 수 없습니다: " +
                             (reason or "unknown"))
        response = api.delete_source(source_id)
        if not isinstance(response, dict):
            raise ValueError("Source 삭제 응답이 JSON 객체가 아닙니다.")
        source_deleted = response.get("source_deleted")
        if source_deleted is None:
            source_deleted = str(response.get("deleted_source_id") or "") == str(source_id)
        survey_points_deleted = int(response.get(
            "survey_points_deleted", response.get("deleted_point_count", 0)
        ) or 0)
        facilities_deleted = int(response.get("facilities_deleted", 0) or 0)
        if source_deleted is not True:
            raise RuntimeError(
                "Source-only response did not confirm source_deleted=true."
            )
        if survey_points_deleted != 0:
            raise RuntimeError(
                "Source-only 삭제 응답이 Survey Point 삭제를 보고했습니다. "
                "서버 삭제 정책을 확인하세요."
            )
        if facilities_deleted != 0:
            raise RuntimeError(
                "Source-only response reported deleted facilities."
            )
        response = {
            **response,
            "source_deleted": True,
            "survey_points_deleted": survey_points_deleted,
            "facilities_deleted": facilities_deleted,
        }
        try:
            self.plugin._pull_and_apply_delta(self.plugin.active_client)
        except Exception:
            # DELETE is already committed and must not be repeated merely
            # because the local revision refresh failed.
            response = {**response, "revision_refresh_pending": True}
        return response

    def refresh(self):
        self.context()
        self.clean()
        self.plugin._sync_active_project(self.plugin.active_client, automatic=True)
        for layer in self.plugin._managed_layers():
            layer.triggerRepaint()
        work = getattr(self.plugin, "work", None)
        if work is not None:
            for page in work.pages.values():
                binding = getattr(page, "binding", None)
                if binding is not None and binding.feature_id is not None:
                    feature = binding.layer.getFeature(binding.feature_id)
                    if feature.isValid():
                        binding.load(feature, force=True)
                    else:
                        binding.clear()
        self.plugin.iface.mapCanvas().refresh()
