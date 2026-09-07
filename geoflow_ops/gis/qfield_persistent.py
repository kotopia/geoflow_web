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


QFIELD_PERSISTENT_PROTOCOL_VERSION = "1.1"


def qfield_install_id(project_id) -> str:
    return f"geoflow-{uuid.UUID(str(project_id))}"


def qfield_schema_fingerprint(alias: str, plan: dict[str, Any]) -> str:
    """Return a stable client-package compatibility fingerprint.

    Ordinary feature edits do not alter this fingerprint. Only profile/layer/
    field contract changes require a package update.
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
    session_handoff_url: str,
    access_expires_at_ms: int,
    schema_fingerprint: str,
    install_id: str,
) -> str:
    marker = "    </GeoFlow>"
    if marker not in text:
        raise RuntimeError("GeoFlow QField project metadata marker is missing")
    additions = f"""      <qfield_session_handoff_url type=\"QString\">{session_handoff_url}</qfield_session_handoff_url>
      <qfield_access_expires_at_ms type=\"QString\">{int(access_expires_at_ms)}</qfield_access_expires_at_ms>
      <qfield_package_version type=\"QString\">{QFIELD_PACKAGE_VERSION}</qfield_package_version>
      <qfield_plugin_runtime_version type=\"QString\">{QFIELD_PLUGIN_RUNTIME_VERSION}</qfield_plugin_runtime_version>
      <qfield_schema_fingerprint type=\"QString\">{schema_fingerprint}</qfield_schema_fingerprint>
      <qfield_install_id type=\"QString\">{install_id}</qfield_install_id>
      <qfield_persistent_protocol type=\"QString\">{QFIELD_PERSISTENT_PROTOCOL_VERSION}</qfield_persistent_protocol>
"""
    return text.replace(marker, additions + marker, 1)


def _inject_qml_persistent_session(text: str) -> str:
    """Layer explicit-auth and sparse-roaming behavior over proven runtime."""

    property_marker = '    property string syncStatus: "idle"\n'
    if property_marker not in text:
        raise RuntimeError("QField persistent property marker is missing")
    text = text.replace(
        property_marker,
        property_marker
        + "    property bool handoffInFlight: false\n"
        + "    property bool serverAuthRequired: false\n"
        + "    property bool packageUpdateRequired: false\n"
        + '    property string packageUpdateReason: ""\n'
        + '    property string sessionHandoffUrl: ""\n'
        + "    property double accessExpiresAtMs: 0\n"
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
        property double accessExpiresAtMs: 0
        property string lastPackageVersion: ""
        property string lastPluginRuntimeVersion: ""
        property string lastSchemaFingerprint: ""
    }

'''
    text = text.replace(toolbar_marker, auth_settings + toolbar_marker, 1)

    config_old = '''        bearerToken = readProjectText("qfield_token")
        roamingPlanUrl = readProjectText("roaming_plan_url")
        roamingCellUrl = readProjectText("roaming_cell_url")
        movementThresholdM = readProjectNumber("movement_threshold_m", 100.0)
        changesetUrl = roamingPlanUrl.replace(/roaming-plan\\/?$/, "changesets/")'''
    config_new = '''        let embeddedAccessToken = readProjectText("qfield_token")
        let embeddedExpiresAtMs = Number(readProjectText("qfield_access_expires_at_ms") || "0")
        sessionHandoffUrl = readProjectText("qfield_session_handoff_url")
        clientPackageVersion = readProjectText("qfield_package_version")
        clientPluginRuntimeVersion = readProjectText("qfield_plugin_runtime_version")
        clientSchemaFingerprint = readProjectText("qfield_schema_fingerprint")
        installId = readProjectText("qfield_install_id")
        roamingPlanUrl = readProjectText("roaming_plan_url")
        roamingCellUrl = readProjectText("roaming_cell_url")
        movementThresholdM = readProjectNumber("movement_threshold_m", 100.0)
        changesetUrl = roamingPlanUrl.replace(/roaming-plan\\/?$/, "changesets/")

        if (authState.accessToken && Number(authState.accessExpiresAtMs || 0) > Date.now()) {
            bearerToken = authState.accessToken
            accessExpiresAtMs = Number(authState.accessExpiresAtMs)
        } else if (embeddedAccessToken && embeddedExpiresAtMs > Date.now()) {
            bearerToken = embeddedAccessToken
            accessExpiresAtMs = embeddedExpiresAtMs
            authState.accessToken = bearerToken
            authState.accessExpiresAtMs = accessExpiresAtMs
        } else {
            bearerToken = ""
            accessExpiresAtMs = 0
            authState.accessToken = ""
            authState.accessExpiresAtMs = 0
            serverAuthRequired = true
        }

        if (localState.lastLocation) {
            let parts = String(localState.lastLocation).split(",")
            if (parts.length === 2) {
                let savedLon = Number(parts[0])
                let savedLat = Number(parts[1])
                if (isFinite(savedLon) && isFinite(savedLat)) {
                    lastLon = savedLon
                    lastLat = savedLat
                }
            }
        }'''
    if config_old not in text:
        raise RuntimeError("QField persistent config marker is missing")
    text = text.replace(config_old, config_new, 1)

    ready_old = '''            serverUrl && projectId && bearerToken && roamingPlanUrl && roamingCellUrl && changesetUrl
        )'''
    ready_new = '''            serverUrl && projectId && sessionHandoffUrl && roamingPlanUrl && roamingCellUrl && changesetUrl
        )'''
    if ready_old not in text:
        raise RuntimeError("QField persistent config-ready marker is missing")
    text = text.replace(ready_old, ready_new, 1)

    reset_old = '''    function resetRoamingStateForFreshTicket() {
        let fingerprint = bearerToken ? bearerToken.slice(-24) : ""
        if (!fingerprint) return
        if (localState.packageTokenFingerprint && localState.packageTokenFingerprint === fingerprint) return
        localState.packageTokenFingerprint = fingerprint
        localState.knownCellsCsv = ""
        localState.lastLocation = ""
        lastViewport = ""
        lastLon = NaN
        lastLat = NaN
        log("fresh package ticket detected; roaming cache state reset")
    }'''
    reset_new = '''    function resetRoamingStateForFreshTicket() {
        let fingerprint = [installId, clientPackageVersion, clientSchemaFingerprint].join("|")
        if (!installId || !clientPackageVersion || !clientSchemaFingerprint) return
        if (localState.packageTokenFingerprint && localState.packageTokenFingerprint === fingerprint) return
        localState.packageTokenFingerprint = fingerprint
        localState.knownCellsCsv = ""
        localState.lastLocation = ""
        lastViewport = ""
        lastLon = NaN
        lastLat = NaN
        log("new QField install contract detected; roaming cache state reset")
    }'''
    if reset_old not in text:
        raise RuntimeError("QField roaming cache reset marker is missing")
    text = text.replace(reset_old, reset_new, 1)

    auth_get_marker = "    function authGet(path, callback, quiet) {"
    if auth_get_marker not in text:
        raise RuntimeError("QField authGet marker is missing")
    handoff_functions = r'''    function sessionAuthorized() {
        return Boolean(bearerToken && accessExpiresAtMs > Date.now())
    }

    function markSessionExpired(showMessage) {
        bearerToken = ""
        accessExpiresAtMs = 0
        authState.accessToken = ""
        authState.accessExpiresAtMs = 0
        serverAuthRequired = true
        syncStatus = "auth_required"
        if (showMessage) {
            toast("GeoFlow 인증 시간이 만료되었습니다 · GeoFlow에 로그인한 뒤 QField에서 열기를 눌러 다시 인증하세요")
        }
        log("QField server session expired; explicit GeoFlow handoff required")
    }

    function applyHandoffDescriptor(body) {
        if (!body || !body.ok || !body.auth) return false
        let token = String(body.auth.token || "")
        let expiresIn = Number(body.auth.expires_in || 0)
        if (!token || expiresIn <= 0) return false
        bearerToken = token
        accessExpiresAtMs = Date.now() + expiresIn * 1000
        authState.accessToken = bearerToken
        authState.accessExpiresAtMs = accessExpiresAtMs
        authState.lastPackageVersion = String(body.package ? body.package.version || "" : "")
        authState.lastPluginRuntimeVersion = String(body.package ? body.package.plugin_runtime || "" : "")
        authState.lastSchemaFingerprint = String(body.package ? body.package.schema_fingerprint || "" : "")
        packageUpdateRequired = Boolean(body.package && body.package.requires_update)
        packageUpdateReason = packageUpdateRequired ? String(body.package.reason || "package_contract_changed") : ""
        serverAuthRequired = false
        authBlocked = false
        if (packageUpdateRequired) {
            toast("GeoFlow QField 업데이트가 필요합니다 · 로컬 변경은 먼저 서버로 전송할 수 있습니다")
            log("package update required: " + packageUpdateReason)
        } else {
            log("explicit GeoFlow handoff accepted; access session active")
        }
        return true
    }

    function exchangeHandoff(handoffToken, callback) {
        if (handoffInFlight || !sessionHandoffUrl || !handoffToken) {
            if (callback) callback(false)
            return
        }
        handoffInFlight = true
        let xhr = new XMLHttpRequest()
        let url = absoluteUrl(sessionHandoffUrl)
        xhr.open("POST", url)
        xhr.setRequestHeader("Accept", "application/json")
        xhr.setRequestHeader("Content-Type", "application/json; charset=utf-8")
        xhr.setRequestHeader("Authorization", "Bearer " + handoffToken)
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            handoffInFlight = false
            if (xhr.status >= 200 && xhr.status < 300) {
                let body = null
                try { body = JSON.parse(xhr.responseText) } catch (parseErr) {}
                let ok = applyHandoffDescriptor(body)
                if (callback) callback(ok)
                return
            }
            log("explicit handoff failed HTTP " + xhr.status)
            if (callback) callback(false)
            toast("GeoFlow QField 재인증에 실패했습니다 · GeoFlow에서 다시 로그인하세요")
        }
        xhr.send(JSON.stringify({
            package_version: clientPackageVersion,
            plugin_runtime_version: clientPluginRuntimeVersion,
            schema_fingerprint: clientSchemaFingerprint,
            install_id: installId
        }))
    }

    function handleExternalAction(action) {
        let text = String(action || "")
        if (text.indexOf("qfield://geoflow") !== 0) return
        let projectMatch = text.match(/[?&]project=([^&]+)/)
        let handoffMatch = text.match(/[?&]handoff=([^&]+)/)
        let requestedProject = projectMatch && projectMatch.length > 1 ? decodeURIComponent(projectMatch[1]) : ""
        let handoffToken = handoffMatch && handoffMatch.length > 1 ? decodeURIComponent(handoffMatch[1]) : ""
        if (requestedProject && canonicalUuid(requestedProject) !== canonicalUuid(projectId)) {
            toast("GeoFlow에서 선택한 프로젝트가 현재 QField 프로젝트와 다릅니다 · 최근 프로젝트 목록에서 해당 프로젝트를 여세요")
            return
        }
        if (!handoffToken) {
            log("GeoFlow handoff action missing token")
            return
        }
        log("explicit GeoFlow handoff received")
        exchangeHandoff(handoffToken, function(ok) {
            if (!ok) return
            syncNow(false, true)
            scheduleRoaming(false)
        })
    }

'''
    text = text.replace(auth_get_marker, handoff_functions + auth_get_marker, 1)

    connections_marker = "    function log(message) {"
    if connections_marker not in text:
        raise RuntimeError("QField Connections marker is missing")
    external_connections = r'''    Connections {
        target: iface
        function onExecuteAction(action) {
            geoflowField.handleExternalAction(action)
        }
    }

'''
    text = text.replace(connections_marker, external_connections + connections_marker, 1)

    roaming_old = '''    function scheduleRoaming(force) {
        if (requestInFlight || !configReady) return
        let viewport = viewportText()
        let pos = currentPosition()
        let moved = false
        if (pos) moved = isNaN(lastLon) || distanceMeters(lastLon, lastLat, pos.lon, pos.lat) >= movementThresholdM
        if (!force && !moved && viewport === lastViewport) return

        let query = []
        if (pos) {
            query.push("lon=" + encodeURIComponent(pos.lon))
            query.push("lat=" + encodeURIComponent(pos.lat))
        }
        if (viewport) query.push("viewport=" + encodeURIComponent(viewport))'''
    roaming_new = '''    function scheduleRoaming(force) {
        if (requestInFlight || !configReady || !sessionAuthorized()) return
        if (packageUpdateRequired) {
            if (force) toast("GeoFlow QField 패키지 업데이트가 필요합니다 · 로컬 변경 동기화 후 GeoFlow에서 업데이트하세요")
            return
        }
        let viewport = viewportText()
        let pos = currentPosition()
        let moved = false
        if (pos) moved = isNaN(lastLon) || distanceMeters(lastLon, lastLat, pos.lon, pos.lat) >= movementThresholdM
        if (!force) {
            if (pos && !moved) return
            if (!pos && viewport === lastViewport) return
        }

        let query = []
        if (pos) {
            query.push("lon=" + encodeURIComponent(pos.lon))
            query.push("lat=" + encodeURIComponent(pos.lat))
        } else if (viewport) {
            query.push("viewport=" + encodeURIComponent(viewport))
        }'''
    if roaming_old not in text:
        raise RuntimeError("QField sparse roaming marker is missing")
    text = text.replace(roaming_old, roaming_new, 1)

    manual_old = '''        syncNow(true, true)
        scheduleRoaming(true)
    }'''
    manual_new = '''        syncNow(true, true)
        scheduleRoaming(false)
    }'''
    if manual_old not in text:
        raise RuntimeError("QField manual roaming marker is missing")
    text = text.replace(manual_old, manual_new, 1)

    sync_guard_old = '''        if (!configReady && !reloadProjectConfig()) {
            if (manual) toast("GeoFlow 프로젝트 연결 정보가 없습니다")
            return
        }
        if (layerBindings.length === 0 && managedLayerDescriptors.length > 0) bindLayers()'''
    sync_guard_new = '''        if (!configReady && !reloadProjectConfig()) {
            if (manual) toast("GeoFlow 프로젝트 연결 정보가 없습니다")
            return
        }
        if (!sessionAuthorized()) {
            serverAuthRequired = true
            syncStatus = "auth_required"
            if (manual) toast("GeoFlow 재인증이 필요합니다 · GeoFlow에 로그인한 뒤 QField에서 열기를 눌러주세요")
            return
        }
        if (layerBindings.length === 0 && managedLayerDescriptors.length > 0) bindLayers()'''
    if sync_guard_old not in text:
        raise RuntimeError("QField sync auth guard marker is missing")
    text = text.replace(sync_guard_old, sync_guard_new, 1)

    post_401_old = '''            if (xhr.status === 401) {
                authBlocked = true
                syncStatus = "auth_required"
                toast("GeoFlow QField 인증 토큰이 만료되었거나 유효하지 않습니다 · 프로젝트를 다시 연결하세요")
                return
            }'''
    post_401_new = '''            if (xhr.status === 401) {
                markSessionExpired(true)
                return
            }'''
    if post_401_old not in text:
        raise RuntimeError("QField changeset 401 marker is missing")
    text = text.replace(post_401_old, post_401_new, 1)

    auth_401_old = '''                if (!quiet && xhr.status === 401) {
                    toast("GeoFlow QField 인증 토큰이 만료되었거나 유효하지 않습니다")
                } else if (!quiet && xhr.status === 403) {'''
    auth_401_new = '''                if (xhr.status === 401) {
                    markSessionExpired(!quiet)
                } else if (!quiet && xhr.status === 403) {'''
    if auth_401_old not in text:
        raise RuntimeError("QField read 401 marker is missing")
    text = text.replace(auth_401_old, auth_401_new, 1)

    init_old = '''        updateUnsyncedCount(projectState())
        toast("GeoFlow Field 0.9.7 연결됨 · 서버 레이어 확인 중")
        scheduleRoaming(true)
        syncNow(false, false)'''
    init_new = '''        updateUnsyncedCount(projectState())
        if (sessionAuthorized()) {
            serverAuthRequired = false
            toast("GeoFlow Field 0.9.7 연결됨 · 인증 유효")
            let pos = currentPosition()
            if (pos && isNaN(lastLon)) {
                lastLon = pos.lon
                lastLat = pos.lat
                localState.lastLocation = pos.lon + "," + pos.lat
            }
            syncNow(false, false)
        } else {
            serverAuthRequired = true
            toast("GeoFlow 로컬 프로젝트 열림 · 서버 사용은 GeoFlow 재인증 후 가능합니다")
        }'''
    if init_old not in text:
        raise RuntimeError("QField initialize marker is missing")
    text = text.replace(init_old, init_new, 1)

    required = (
        "function sessionAuthorized()",
        "function exchangeHandoff(handoffToken, callback)",
        "explicit GeoFlow handoff required",
        "qfield_session_handoff_url",
        "qfield_access_expires_at_ms",
        "new QField install contract detected",
        "if (pos && !moved) return",
        "else if (viewport)",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise RuntimeError("Explicit-auth QField runtime render incomplete: " + ", ".join(missing))
    if "refreshToken" in text or "sessionRefreshTimer" in text or "refreshSession(" in text:
        raise RuntimeError("Autonomous QField refresh path must not exist")
    return text


def upgrade_qfield_bootstrap_zip(
    zip_path: Path,
    *,
    session_handoff_url: str,
    access_expires_at_ms: int,
    schema_fingerprint: str,
    install_id: str,
) -> Path:
    """Upgrade a bootstrap ZIP to explicit-auth persistent-project contract."""

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
                        session_handoff_url=session_handoff_url,
                        access_expires_at_ms=access_expires_at_ms,
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
                        "- access authorization is non-renewing and expires after the GeoFlow access window.\n"
                        "- after expiry, authenticate in GeoFlow and launch QField again; local edits remain queued.\n"
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
