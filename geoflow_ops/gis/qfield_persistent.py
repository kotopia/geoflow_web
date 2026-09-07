from __future__ import annotations

import hashlib
import json
import os
import tempfile
import uuid
import zipfile
from pathlib import Path
from typing import Any

from .gpkg_snapshot_v2 import _layer_specs
from .qfield_package import (
    PROJECT_BASENAME,
    QFIELD_PACKAGE_VERSION,
    QFIELD_PLUGIN_RUNTIME_VERSION,
)


QFIELD_PERSISTENT_PROTOCOL_VERSION = "1.0"
QFIELD_REFRESH_INTERVAL_MS = 4 * 60 * 60 * 1000


def qfield_install_id(project_id) -> str:
    return f"geoflow-{uuid.UUID(str(project_id))}"


def qfield_schema_fingerprint(alias: str, plan: dict[str, Any]) -> str:
    """Return a stable client-package compatibility fingerprint.

    Data changes do not alter this fingerprint. Only project profile/layer/field
    contract changes require a new QField package.
    """

    specs = _layer_specs(alias, plan)
    payload = {
        "profile": (plan.get("profile") or {}).get("code") or "",
        "layers": [
            {
                "standard_name": spec.standard_name,
                "physical_name": spec.physical_name,
                "geometry_kind": spec.geometry_kind,
                "fields": [
                    {
                        "name": field.name,
                        "data_type": field.data_type,
                        "editable": bool(field.editable),
                        "visible": bool(field.visible),
                        "sort_order": int(field.sort_order),
                    }
                    for field in spec.fields
                ],
            }
            for spec in specs
        ],
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _inject_qgs_persistent_metadata(
    text: str,
    *,
    refresh_token: str,
    session_refresh_url: str,
    schema_fingerprint: str,
    install_id: str,
) -> str:
    marker = "    </GeoFlow>"
    if marker not in text:
        raise RuntimeError("GeoFlow QField project metadata marker is missing")
    additions = f"""      <qfield_refresh_token type=\"QString\">{refresh_token}</qfield_refresh_token>
      <qfield_session_refresh_url type=\"QString\">{session_refresh_url}</qfield_session_refresh_url>
      <qfield_package_version type=\"QString\">{QFIELD_PACKAGE_VERSION}</qfield_package_version>
      <qfield_plugin_runtime_version type=\"QString\">{QFIELD_PLUGIN_RUNTIME_VERSION}</qfield_plugin_runtime_version>
      <qfield_schema_fingerprint type=\"QString\">{schema_fingerprint}</qfield_schema_fingerprint>
      <qfield_install_id type=\"QString\">{install_id}</qfield_install_id>
      <qfield_persistent_protocol type=\"QString\">{QFIELD_PERSISTENT_PROTOCOL_VERSION}</qfield_persistent_protocol>
"""
    return text.replace(marker, additions + marker, 1)


def _inject_qml_persistent_session(text: str) -> str:
    """Layer persistent auth/update behavior over the proven QField runtime."""

    property_marker = '    property string syncStatus: "idle"\n'
    if property_marker not in text:
        raise RuntimeError("QField persistent property marker is missing")
    text = text.replace(
        property_marker,
        property_marker
        + "    property bool sessionRefreshInFlight: false\n"
        + "    property bool packageUpdateRequired: false\n"
        + '    property string packageUpdateReason: ""\n'
        + '    property string refreshToken: ""\n'
        + '    property string sessionRefreshUrl: ""\n'
        + '    property string clientPackageVersion: ""\n'
        + '    property string clientPluginRuntimeVersion: ""\n'
        + '    property string clientSchemaFingerprint: ""\n'
        + '    property string installId: ""\n',
        1,
    )

    toolbar_marker = "    QfToolButton {\n        id: syncButton"
    if toolbar_marker not in text:
        raise RuntimeError("QField persistent toolbar marker is missing")
    auth_settings = r'''    Settings {
        id: authState
        category: "GeoFlowFieldAuth/" + geoflowField.projectId
        property string accessToken: ""
        property string refreshToken: ""
        property double accessExpiresAtMs: 0
        property string lastPackageVersion: ""
        property string lastPluginRuntimeVersion: ""
        property string lastSchemaFingerprint: ""
    }

'''
    text = text.replace(toolbar_marker, auth_settings + toolbar_marker, 1)

    timer_marker = "    Timer {\n        id: roamingTimer"
    if timer_marker not in text:
        raise RuntimeError("QField persistent timer marker is missing")
    refresh_timer = f'''    Timer {{
        id: sessionRefreshTimer
        interval: {QFIELD_REFRESH_INTERVAL_MS}
        repeat: true
        running: true
        onTriggered: geoflowField.refreshSession(null, true)
    }}

'''
    text = text.replace(timer_marker, refresh_timer + timer_marker, 1)

    config_old = '''        bearerToken = readProjectText("qfield_token")
        roamingPlanUrl = readProjectText("roaming_plan_url")
        roamingCellUrl = readProjectText("roaming_cell_url")
        movementThresholdM = readProjectNumber("movement_threshold_m", 100.0)
        changesetUrl = roamingPlanUrl.replace(/roaming-plan\\/?$/, "changesets/")'''
    config_new = '''        let embeddedAccessToken = readProjectText("qfield_token")
        let embeddedRefreshToken = readProjectText("qfield_refresh_token")
        bearerToken = authState.accessToken || embeddedAccessToken
        refreshToken = authState.refreshToken || embeddedRefreshToken
        sessionRefreshUrl = readProjectText("qfield_session_refresh_url")
        clientPackageVersion = readProjectText("qfield_package_version")
        clientPluginRuntimeVersion = readProjectText("qfield_plugin_runtime_version")
        clientSchemaFingerprint = readProjectText("qfield_schema_fingerprint")
        installId = readProjectText("qfield_install_id")
        roamingPlanUrl = readProjectText("roaming_plan_url")
        roamingCellUrl = readProjectText("roaming_cell_url")
        movementThresholdM = readProjectNumber("movement_threshold_m", 100.0)
        changesetUrl = roamingPlanUrl.replace(/roaming-plan\\/?$/, "changesets/")'''
    if config_old not in text:
        raise RuntimeError("QField persistent config marker is missing")
    text = text.replace(config_old, config_new, 1)

    ready_old = '''            serverUrl && projectId && bearerToken && roamingPlanUrl && roamingCellUrl && changesetUrl
        )'''
    ready_new = '''            serverUrl && projectId && bearerToken && refreshToken && sessionRefreshUrl && roamingPlanUrl && roamingCellUrl && changesetUrl
        )'''
    if ready_old not in text:
        raise RuntimeError("QField persistent config-ready marker is missing")
    text = text.replace(ready_old, ready_new, 1)

    auth_get_marker = "    function authGet(path, callback, quiet) {"
    if auth_get_marker not in text:
        raise RuntimeError("QField persistent authGet marker is missing")
    refresh_functions = r'''    function applySessionDescriptor(body) {
        if (!body || !body.ok || !body.auth) return false
        bearerToken = String(body.auth.token || "")
        refreshToken = String(body.auth.refresh_token || refreshToken || "")
        if (!bearerToken || !refreshToken) return false

        authState.accessToken = bearerToken
        authState.refreshToken = refreshToken
        authState.accessExpiresAtMs = Date.now() + Number(body.auth.expires_in || 0) * 1000
        authState.lastPackageVersion = String(body.package ? body.package.version || "" : "")
        authState.lastPluginRuntimeVersion = String(body.package ? body.package.plugin_runtime || "" : "")
        authState.lastSchemaFingerprint = String(body.package ? body.package.schema_fingerprint || "" : "")

        packageUpdateRequired = Boolean(body.package && body.package.requires_update)
        packageUpdateReason = packageUpdateRequired ? String(body.package.reason || "package_contract_changed") : ""
        authBlocked = false
        if (packageUpdateRequired) {
            log("package update required: " + packageUpdateReason)
            toast("GeoFlow QField 업데이트가 필요합니다 · 현재 로컬 변경은 먼저 서버로 전송할 수 있습니다")
        } else {
            log("persistent session refreshed")
        }
        return true
    }

    function refreshSession(callback, quiet) {
        if (sessionRefreshInFlight || !sessionRefreshUrl || !refreshToken) {
            if (callback) callback(Boolean(bearerToken))
            return
        }
        sessionRefreshInFlight = true
        let xhr = new XMLHttpRequest()
        let url = absoluteUrl(sessionRefreshUrl)
        xhr.open("POST", url)
        xhr.setRequestHeader("Accept", "application/json")
        xhr.setRequestHeader("Content-Type", "application/json; charset=utf-8")
        if (bearerToken) xhr.setRequestHeader("Authorization", "Bearer " + bearerToken)
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            sessionRefreshInFlight = false
            if (xhr.status >= 200 && xhr.status < 300) {
                let body = null
                try { body = JSON.parse(xhr.responseText) } catch (parseErr) {}
                let ok = applySessionDescriptor(body)
                if (callback) callback(ok)
                return
            }
            log("session refresh failed HTTP " + xhr.status)
            if (xhr.status === 401 || xhr.status === 403) {
                authBlocked = true
                if (!quiet) toast("GeoFlow QField 연결 권한이 만료되었습니다 · GeoFlow에서 프로젝트 연결을 다시 시작하세요")
            }
            if (callback) callback(false)
        }
        xhr.send(JSON.stringify({
            refresh_token: refreshToken,
            package_version: clientPackageVersion,
            plugin_runtime_version: clientPluginRuntimeVersion,
            schema_fingerprint: clientSchemaFingerprint,
            install_id: installId
        }))
    }

    function handleExternalAction(action) {
        let text = String(action || "")
        if (text.indexOf("qfield://geoflow") !== 0) return
        let match = text.match(/[?&]project=([^&]+)/)
        let requestedProject = match && match.length > 1 ? decodeURIComponent(match[1]) : ""
        if (requestedProject && canonicalUuid(requestedProject) !== canonicalUuid(projectId)) {
            toast("GeoFlow에서 선택한 프로젝트가 현재 QField 프로젝트와 다릅니다 · 최근 프로젝트 목록에서 해당 프로젝트를 여세요")
            return
        }
        log("GeoFlow persistent handoff received")
        refreshSession(function(ok) {
            if (!ok) return
            syncNow(false, true)
            if (!packageUpdateRequired) scheduleRoaming(true)
        }, false)
    }

'''
    text = text.replace(auth_get_marker, refresh_functions + auth_get_marker, 1)

    connections_marker = "    function log(message) {"
    if connections_marker not in text:
        raise RuntimeError("QField persistent Connections marker is missing")
    external_connections = r'''    Connections {
        target: iface
        function onExecuteAction(action) {
            geoflowField.handleExternalAction(action)
        }
    }

'''
    text = text.replace(connections_marker, external_connections + connections_marker, 1)

    roaming_old = '''    function scheduleRoaming(force) {
        if (requestInFlight || !configReady) return'''
    roaming_new = '''    function scheduleRoaming(force) {
        if (requestInFlight || !configReady) return
        if (packageUpdateRequired) {
            if (force) toast("GeoFlow QField 패키지 업데이트가 필요합니다 · 로컬 변경 동기화 후 GeoFlow에서 업데이트하세요")
            return
        }'''
    if roaming_old not in text:
        raise RuntimeError("QField persistent roaming marker is missing")
    text = text.replace(roaming_old, roaming_new, 1)

    init_old = '''        updateUnsyncedCount(projectState())
        toast("GeoFlow Field 0.9.7 연결됨 · 서버 레이어 확인 중")
        scheduleRoaming(true)
        syncNow(false, false)'''
    init_new = '''        updateUnsyncedCount(projectState())
        toast("GeoFlow Field 0.9.7 연결됨 · 영구 프로젝트 세션 확인 중")
        refreshSession(function(ok) {
            if (!ok && !bearerToken) return
            syncNow(false, false)
            if (!packageUpdateRequired) scheduleRoaming(true)
        }, true)'''
    if init_old not in text:
        raise RuntimeError("QField persistent initialize marker is missing")
    text = text.replace(init_old, init_new, 1)

    post_401_old = '''            if (xhr.status === 401) {
                authBlocked = true
                syncStatus = "auth_required"
                toast("GeoFlow QField 인증 토큰이 만료되었거나 유효하지 않습니다 · 프로젝트를 다시 연결하세요")
                return
            }'''
    post_401_new = '''            if (xhr.status === 401) {
                authBlocked = false
                syncStatus = "auth_required"
                log("access ticket expired during changeset; refreshing persistent session")
                refreshSession(function(ok) {
                    if (ok) {
                        authBlocked = false
                        syncNow(false, true)
                    }
                }, false)
                return
            }'''
    if post_401_old not in text:
        raise RuntimeError("QField persistent changeset 401 marker is missing")
    text = text.replace(post_401_old, post_401_new, 1)

    auth_401_old = '''                if (!quiet && xhr.status === 401) {
                    toast("GeoFlow QField 인증 토큰이 만료되었거나 유효하지 않습니다")'''
    auth_401_new = '''                if (xhr.status === 401) {
                    authBlocked = false
                    log("access ticket expired during read; refreshing persistent session")
                    refreshSession(function(ok) {
                        if (ok) scheduleRoaming(true)
                    }, quiet)
                    if (!quiet) toast("GeoFlow QField 인증을 갱신하고 있습니다")'''
    if auth_401_old not in text:
        raise RuntimeError("QField persistent read 401 marker is missing")
    text = text.replace(auth_401_old, auth_401_new, 1)

    required = (
        "GeoFlowFieldAuth/",
        "function refreshSession(callback, quiet)",
        "function handleExternalAction(action)",
        "packageUpdateRequired",
        "qfield_session_refresh_url",
        "qfield_schema_fingerprint",
        'Authorization", "Bearer " + bearerToken',
        "access ticket expired during changeset",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise RuntimeError("Persistent QField runtime render incomplete: " + ", ".join(missing))
    return text


def upgrade_qfield_bootstrap_zip(
    zip_path: Path,
    *,
    refresh_token: str,
    session_refresh_url: str,
    schema_fingerprint: str,
    install_id: str,
) -> Path:
    """Upgrade a proven bootstrap ZIP to the persistent-project contract."""

    source = Path(zip_path)
    temp = tempfile.NamedTemporaryFile(
        prefix="geoflow-qfield-persistent-",
        suffix=".zip",
        delete=False,
    )
    output = Path(temp.name)
    temp.close()
    try:
        with zipfile.ZipFile(source, "r") as src, zipfile.ZipFile(
            output,
            "w",
            compression=zipfile.ZIP_DEFLATED,
        ) as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename == f"{PROJECT_BASENAME}.qgs":
                    text = data.decode("utf-8")
                    text = _inject_qgs_persistent_metadata(
                        text,
                        refresh_token=refresh_token,
                        session_refresh_url=session_refresh_url,
                        schema_fingerprint=schema_fingerprint,
                        install_id=install_id,
                    )
                    data = text.encode("utf-8")
                elif info.filename == f"{PROJECT_BASENAME}.qml":
                    text = _inject_qml_persistent_session(data.decode("utf-8"))
                    data = text.encode("utf-8")
                elif info.filename == "README.txt":
                    text = data.decode("utf-8")
                    text += (
                        f"- persistent protocol: {QFIELD_PERSISTENT_PROTOCOL_VERSION}\n"
                        f"- install id: {install_id}\n"
                        "- project folder is persistent; ordinary data edits do not require package re-import.\n"
                        "- access tickets refresh automatically while current central membership remains valid.\n"
                    )
                    data = text.encode("utf-8")
                dst.writestr(info, data)
        os.replace(output, source)
        return source
    except Exception:
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        raise
