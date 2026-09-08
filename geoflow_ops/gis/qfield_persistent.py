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
from .qfield_package import PROJECT_BASENAME, QFIELD_PACKAGE_VERSION, QFIELD_PLUGIN_RUNTIME_VERSION


QFIELD_PERSISTENT_PROTOCOL_VERSION = "1.2"


def qfield_install_id(project_id) -> str:
    return f"geoflow-{uuid.UUID(str(project_id))}"


def qfield_schema_fingerprint(alias: str, plan: dict[str, Any]) -> str:
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
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:24]


def _inject_qgs_persistent_metadata(
    text: str,
    *,
    claim_token: str,
    session_claim_url: str,
    delta_url: str,
    access_expires_at_ms: int,
    snapshot_revision: int,
    schema_fingerprint: str,
    install_id: str,
) -> str:
    marker = "    </GeoFlow>"
    if marker not in text:
        raise RuntimeError("GeoFlow QField project metadata marker is missing")
    additions = f"""      <qfield_claim_token type=\"QString\">{claim_token}</qfield_claim_token>
      <qfield_session_claim_url type=\"QString\">{session_claim_url}</qfield_session_claim_url>
      <qfield_delta_url type=\"QString\">{delta_url}</qfield_delta_url>
      <qfield_access_expires_at_ms type=\"QString\">{int(access_expires_at_ms)}</qfield_access_expires_at_ms>
      <qfield_snapshot_revision type=\"QString\">{int(snapshot_revision)}</qfield_snapshot_revision>
      <qfield_package_version type=\"QString\">{QFIELD_PACKAGE_VERSION}</qfield_package_version>
      <qfield_plugin_runtime_version type=\"QString\">{QFIELD_PLUGIN_RUNTIME_VERSION}</qfield_plugin_runtime_version>
      <qfield_schema_fingerprint type=\"QString\">{schema_fingerprint}</qfield_schema_fingerprint>
      <qfield_install_id type=\"QString\">{install_id}</qfield_install_id>
      <qfield_persistent_protocol type=\"QString\">{QFIELD_PERSISTENT_PROTOCOL_VERSION}</qfield_persistent_protocol>
"""
    return text.replace(marker, additions + marker, 1)


def _inject_qml_persistent_session(text: str) -> str:
    if "import org.qfield.core" not in text:
        import_marker = "import org.qfield\n"
        if import_marker not in text:
            raise RuntimeError("QField import marker missing")
        text = text.replace(import_marker, import_marker + "import org.qfield.core\n", 1)

    property_marker = '    property string syncStatus: "idle"\n'
    if property_marker not in text:
        raise RuntimeError("QField persistent property marker missing")
    text = text.replace(
        property_marker,
        property_marker
        + "    property bool claimInFlight: false\n"
        + "    property var claimRequest: null\n"
        + "    property double claimStartedAtMs: 0\n"
        + "    property bool deltaInFlight: false\n"
        + "    property var deltaRequest: null\n"
        + "    property double deltaStartedAtMs: 0\n"
        + "    property double nextDeltaAtMs: 0\n"
        + "    property int deltaIdleDelayMs: 15000\n"
        + "    property bool deltaSnapshotRequired: false\n"
        + "    property bool serverAuthRequired: false\n"
        + "    property bool packageUpdateRequired: false\n"
        + '    property string packageUpdateReason: ""\n'
        + '    property string claimToken: ""\n'
        + '    property string sessionClaimUrl: ""\n'
        + '    property string deltaUrl: ""\n'
        + "    property double accessExpiresAtMs: 0\n"
        + "    property int snapshotRevision: 0\n"
        + '    property string clientPackageVersion: ""\n'
        + '    property string clientPluginRuntimeVersion: ""\n'
        + '    property string clientSchemaFingerprint: ""\n'
        + '    property string installId: ""\n',
        1,
    )

    toolbar_marker = "    QfToolButton {\n        id: syncButton"
    if toolbar_marker not in text:
        raise RuntimeError("QField toolbar marker missing")
    helpers = r'''    Settings {
        id: authState
        category: "GeoFlowFieldAuth/" + geoflowField.projectId
        property string accessToken: ""
        property double accessExpiresAtMs: 0
        property string lastPackageVersion: ""
        property string lastPluginRuntimeVersion: ""
        property string lastSchemaFingerprint: ""
    }

    QfFeatureModel {
        id: deltaFeatureModel
        project: qgisProject
    }

'''
    text = text.replace(toolbar_marker, helpers + toolbar_marker, 1)

    roaming_timer_old = '''    Timer {
        id: roamingTimer
        interval: 8000
        repeat: true
        running: true
        onTriggered: geoflowField.scheduleRoaming(false)
    }'''
    roaming_timer_new = '''    Timer {
        id: roamingTimer
        interval: 8000
        repeat: false
        running: false
        onTriggered: geoflowField.scheduleRoaming(false)
    }'''
    if roaming_timer_old not in text:
        raise RuntimeError("QField roaming timer marker missing")
    text = text.replace(roaming_timer_old, roaming_timer_new, 1)
    text = text.replace("            roamingTimer.restart()", "            roamingTimer.stop()")

    sync_timer_old = '''    Timer {
        id: syncTimer
        interval: 3000
        repeat: true
        running: true
        onTriggered: geoflowField.syncNow(false, false)
    }'''
    sync_timer_new = '''    Timer {
        id: syncTimer
        interval: 3000
        repeat: true
        running: geoflowField.unsyncedCount > 0
        onTriggered: geoflowField.syncNow(false, false)
    }'''
    if sync_timer_old not in text:
        raise RuntimeError("QField sync timer marker missing")
    text = text.replace(sync_timer_old, sync_timer_new, 1)

    config_old = '''        bearerToken = readProjectText("qfield_token")
        roamingPlanUrl = readProjectText("roaming_plan_url")
        roamingCellUrl = readProjectText("roaming_cell_url")
        movementThresholdM = readProjectNumber("movement_threshold_m", 100.0)
        changesetUrl = roamingPlanUrl.replace(/roaming-plan\\/?$/, "changesets/")'''
    config_new = '''        let embeddedAccessToken = readProjectText("qfield_token")
        let embeddedExpiresAtMs = Number(readProjectText("qfield_access_expires_at_ms") || "0")
        claimToken = readProjectText("qfield_claim_token")
        sessionClaimUrl = readProjectText("qfield_session_claim_url")
        deltaUrl = readProjectText("qfield_delta_url")
        snapshotRevision = Number(readProjectText("qfield_snapshot_revision") || "0")
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

        let state = projectState()
        if (!state.outbox && !state.conflict && Object.keys(state.pending || {}).length === 0 && Number(state.base_revision || 0) === 0) {
            state.base_revision = Math.max(0, Number(snapshotRevision || 0))
            saveProjectState(state)
        }'''
    if config_old not in text:
        raise RuntimeError("QField config marker missing")
    text = text.replace(config_old, config_new, 1)

    ready_old = '''            serverUrl && projectId && bearerToken && roamingPlanUrl && roamingCellUrl && changesetUrl
        )'''
    ready_new = '''            serverUrl && projectId && claimToken && sessionClaimUrl && deltaUrl && roamingPlanUrl && roamingCellUrl && changesetUrl
        )'''
    if ready_old not in text:
        raise RuntimeError("QField config-ready marker missing")
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
        raise RuntimeError("QField cache reset marker missing")
    text = text.replace(reset_old, reset_new, 1)

    auth_get_marker = "    function authGet(path, callback, quiet) {"
    if auth_get_marker not in text:
        raise RuntimeError("QField authGet marker missing")

    runtime = r'''    Timer {
        interval: 2000
        repeat: true
        running: geoflowField.sessionAuthorized() && Qt.application.state === Qt.ApplicationActive
        onTriggered: {
            if (Date.now() >= geoflowField.nextDeltaAtMs && !geoflowField.deltaSnapshotRequired)
                geoflowField.pullDelta(false)
        }
    }
    Timer {
        interval: 1000
        repeat: true
        running: geoflowField.deltaInFlight || geoflowField.claimInFlight
        onTriggered: {
            geoflowField.expireStalledDelta()
            geoflowField.expireStalledClaim()
        }
    }
    function scheduleDeltaCheck(changed, failed) {
        deltaIdleDelayMs = changed ? 15000 : (failed ? 60000 : Math.min(60000, deltaIdleDelayMs * 2))
        nextDeltaAtMs = Date.now() + deltaIdleDelayMs
    }
    function expireStalledDelta() {
        if (!deltaInFlight || !deltaRequest || Date.now() - deltaStartedAtMs < 30000) return
        let stalled = deltaRequest
        deltaRequest = null
        deltaInFlight = false
        scheduleDeltaCheck(false, true)
        stalled.abort()
        log("delta timeout; local changes and cursor retained")
    }
    function expireStalledClaim() {
        if (!claimInFlight || !claimRequest || Date.now() - claimStartedAtMs < 30000) return
        let stalled = claimRequest
        claimRequest = null
        claimInFlight = false
        stalled.abort()
        log("session claim timeout; retry from GeoFlow or foreground")
    }
    function canApplyDelta(requestProject, requestServer, since, state) {
        return requestProject === projectId && requestServer === serverUrl && sessionAuthorized() &&
            !syncInFlight && !hasUncommittedEdits() && !state.conflict && !state.outbox &&
            Object.keys(state.pending || {}).length === 0 && Number(state.base_revision || 0) === since
    }
    function sessionAuthorized() {
        return Boolean(bearerToken && accessExpiresAtMs > Date.now())
    }

    function markSessionExpired(showMessage) {
        bearerToken = ""
        accessExpiresAtMs = 0
        authState.accessToken = ""
        authState.accessExpiresAtMs = 0
        serverAuthRequired = true
        syncStatus = "auth_required"
        if (showMessage) toast("GeoFlow 인증이 만료되었습니다 · GeoFlow 로그인 후 QField에서 열기를 눌러주세요")
        log("QField server session expired; explicit GeoFlow handoff required")
    }

    function applySessionDescriptor(body) {
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
        log("pending GeoFlow handoff claimed; access session active")
        return true
    }

    function claimPendingSession(showMessage, callback) {
        if (claimInFlight || !sessionClaimUrl || !claimToken) {
            if (callback) callback(false)
            return
        }
        claimInFlight = true
        let xhr = new XMLHttpRequest()
        claimRequest = xhr
        claimStartedAtMs = Date.now()
        let claimProject = projectId
        let claimServer = serverUrl
        let url = absoluteUrl(sessionClaimUrl)
        xhr.open("POST", url)
        xhr.setRequestHeader("Accept", "application/json")
        xhr.setRequestHeader("Content-Type", "application/json; charset=utf-8")
        xhr.setRequestHeader("Authorization", "Bearer " + claimToken)
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            if (claimRequest !== xhr) return
            claimRequest = null
            claimInFlight = false
            if (claimProject !== projectId || claimServer !== serverUrl) return
            let body = null
            try { body = JSON.parse(xhr.responseText) } catch (err) {}
            if (xhr.status >= 200 && xhr.status < 300) {
                if (body && body.pending === false) {
                    log("no pending GeoFlow handoff")
                    if (callback) callback(false)
                    return
                }
                let ok = applySessionDescriptor(body)
                if (ok && showMessage) toast("GeoFlow 재인증 완료 · 12시간 서버 연결")
                if (callback) callback(ok)
                return
            }
            log("pending handoff claim failed HTTP " + xhr.status)
            if (showMessage && xhr.status !== 0) toast("GeoFlow 재인증 확인 실패: HTTP " + xhr.status)
            if (callback) callback(false)
        }
        xhr.send(JSON.stringify({
            package_version: clientPackageVersion,
            plugin_runtime_version: clientPluginRuntimeVersion,
            schema_fingerprint: clientSchemaFingerprint,
            install_id: installId
        }))
    }

    function deltaLayer(row) {
        let physical = String(row.physical_name || "")
        if (physical) {
            try {
                let matches = qgisProject.mapLayersByName(physical)
                if (matches && matches.length > 0) return matches[0]
            } catch (err) {}
        }
        let standard = String(row.layer || "").toUpperCase()
        for (let i = 0; i < layerBindings.length; i++) {
            if (String(layerBindings[i].standard || "").toUpperCase() === standard) return layerBindings[i].layer
        }
        return null
    }

    function featureByObjectId(layer, objectId) {
        if (!layer || !objectId) return null
        let escaped = String(objectId).replace(/'/g, "''")
        let iterator = null
        try {
            iterator = LayerUtils.createFeatureIteratorFromExpression(layer, "\"id\" = '" + escaped + "'")
            if (iterator.hasNext()) return iterator.next()
        } catch (err) {
            log("delta feature lookup failed: " + err)
        } finally {
            if (iterator) try { iterator.close() } catch (closeErr) {}
        }
        return null
    }

    function applyDeltaChange(row, state) {
        if (!row) return true
        if (String(row.client_id || "") === String(state.client_id || "")) return true
        let layer = deltaLayer(row)
        if (!layer) {
            log("delta layer missing " + String(row.layer || row.physical_name || ""))
            return false
        }
        let action = String(row.action || "").toLowerCase()
        let objectId = canonicalUuid(row.id || "")
        if (!objectId) return false
        let current = featureByObjectId(layer, objectId)

        captureSuppressed = true
        try {
            if (action === "delete") {
                if (!current) return true
                return Boolean(LayerUtils.deleteFeature(qgisProject, layer, current.id, true))
            }

            if (action === "create" && !current) {
                let geometry = GeometryUtils.createGeometryFromWkt(String(row.geometry_wkt || ""))
                if (!geometry || geometry.isNull) {
                    log("delta create missing geometry " + objectId)
                    return false
                }
                let feature = FeatureUtils.createFeature(layer, geometry)
                feature.setAttribute("id", objectId)
                feature.setAttribute("project_id", projectId)
                let attrs = row.attributes || {}
                for (let name in attrs) {
                    if (!Object.prototype.hasOwnProperty.call(attrs, name)) continue
                    try { feature.setAttribute(name, attrs[name]) } catch (attrErr) {}
                }
                return Boolean(LayerUtils.addFeature(layer, feature))
            }

            if (!current) {
                log("delta update target missing " + objectId)
                return false
            }

            if (row.geometry_wkt) {
                let geometry2 = GeometryUtils.createGeometryFromWkt(String(row.geometry_wkt))
                if (!geometry2 || geometry2.isNull) return false
                deltaFeatureModel.currentLayer = layer
                deltaFeatureModel.feature = current
                if (!deltaFeatureModel.changeGeometry(geometry2) || !deltaFeatureModel.save(true)) {
                    log("delta geometry save failed " + objectId)
                    return false
                }
                current = featureByObjectId(layer, objectId) || current
            }

            let attrs2 = row.attributes || {}
            let fields = layer.fields()
            let currentFid = typeof current.id === "function" ? current.id() : current.id
            if (Object.keys(attrs2).length > 0) {
                if (!layer.startEditing()) {
                    log("delta attribute edit start failed " + objectId)
                    return false
                }
                for (let name2 in attrs2) {
                    if (!Object.prototype.hasOwnProperty.call(attrs2, name2) || protectedField(name2)) continue
                    let idx = fields.indexOf(name2)
                    if (idx < 0 || !layer.changeAttributeValue(currentFid, idx, attrs2[name2])) {
                        layer.rollBack()
                        log("delta attribute unavailable or rejected " + name2)
                        return false
                    }
                }
                if (!layer.commitChanges(true)) {
                    log("delta attribute commit failed " + objectId)
                    return false
                }
            }
            return true
        } catch (err) {
            log("delta apply failed " + objectId + ": " + err)
            return false
        } finally {
            captureSuppressed = false
        }
    }

    function pullDelta(manual) {
        if (deltaInFlight || syncInFlight || hasUncommittedEdits() || !configReady || !sessionAuthorized()) return
        if (!manual && (deltaSnapshotRequired || Date.now() < nextDeltaAtMs)) return
        let state = projectState()
        if (state.conflict || state.outbox || Object.keys(state.pending || {}).length > 0) return
        deltaInFlight = true
        nextDeltaAtMs = Date.now() + 15000
        let requestProject = projectId
        let requestServer = serverUrl
        let since = Math.max(0, Number(state.base_revision || 0))
        let xhr = new XMLHttpRequest()
        deltaRequest = xhr
        deltaStartedAtMs = Date.now()
        let url = absoluteUrl(deltaUrl) + "?since=" + encodeURIComponent(since) + "&limit=1000"
        xhr.open("GET", url)
        xhr.setRequestHeader("Accept", "application/json")
        xhr.setRequestHeader("Authorization", "Bearer " + bearerToken)
        xhr.onreadystatechange = function() {
            if (xhr.readyState !== XMLHttpRequest.DONE) return
            if (deltaRequest !== xhr) return
            deltaRequest = null
            deltaInFlight = false
            if (requestProject !== projectId || requestServer !== serverUrl) return
            if (xhr.status === 401) {
                markSessionExpired(manual)
                return
            }
            if (xhr.status < 200 || xhr.status >= 300) {
                scheduleDeltaCheck(false, true)
                log("delta pull failed HTTP " + xhr.status)
                if (manual && xhr.status !== 0) toast("GeoFlow 변경분 수신 실패: HTTP " + xhr.status)
                return
            }
            let body = null
            try { body = JSON.parse(xhr.responseText) } catch (err) {}
            if (!body || !body.ok) { scheduleDeltaCheck(false, true); return }
            if (body.snapshot_required) {
                deltaSnapshotRequired = true
                log("delta history gap requires fresh snapshot")
                if (manual) toast("GeoFlow 변경 이력이 오래되어 전체 스냅샷 업데이트가 필요합니다")
                return
            }
            state = projectState()
            if (!canApplyDelta(requestProject, requestServer, since, state)) {
                scheduleDeltaCheck(false, false)
                log("delta deferred; local edit or project state changed during request")
                return
            }
            deltaSnapshotRequired = false
            let rows = body.changes || []
            let next = since
            let applied = 0
            for (let i = 0; i < rows.length; i++) {
                let row = rows[i]
                if (!applyDeltaChange(row, state)) break
                next = Number(row.revision || next)
                applied += 1
            }
            state.base_revision = Math.max(Number(state.base_revision || 0), next)
            saveProjectState(state)
            if (applied > 0) {
                mapCanvas.refresh()
                bindLayers()
                rebuildPollingBaseline()
                log("delta applied count=" + applied + " revision=" + state.base_revision)
            }
            scheduleDeltaCheck(applied > 0, false)
            if (body.has_more && rows.length > 0 && applied === rows.length) {
                nextDeltaAtMs = 0
                pullDelta(manual)
            } else if (manual) {
                toast(applied > 0 ? "GeoFlow 변경분 " + applied + "건 수신 완료" : "GeoFlow 서버와 최신 상태입니다")
            }
        }
        xhr.send()
    }

'''
    text = text.replace(auth_get_marker, runtime + auth_get_marker, 1)

    # The browser resumes QField without an import parameter. The active
    # project claims the server-staged handoff on foreground/config load.
    text = text.replace("        syncNow(true, true)\n        scheduleRoaming(true)", "        syncNow(true, true)", 1)

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
            claimPendingSession(manual, function(ok) {
                if (ok) geoflowField.syncNow(manual, acceptedEdit)
                else if (manual) toast("GeoFlow 재인증이 필요합니다 · GeoFlow 로그인 후 QField에서 열기를 눌러주세요")
            })
            return
        }
        if (layerBindings.length === 0) bindLayers()'''
    if sync_guard_old not in text:
        raise RuntimeError("QField sync auth guard marker missing")
    text = text.replace(sync_guard_old, sync_guard_new, 1)

    no_payload_old = '''        if (!payload) {
            syncStatus = "synced"
            if (manual) toast("GeoFlow: 동기화할 로컬 변경이 없습니다")
            return
        }
        postOutbox(payload, manual)'''
    no_payload_new = '''        if (!payload) {
            syncStatus = "synced"
            pullDelta(manual)
            return
        }
        postOutbox(payload, manual)'''
    if no_payload_old not in text:
        raise RuntimeError("QField no-payload marker missing")
    text = text.replace(no_payload_old, no_payload_new, 1)

    base_old = '                    state.base_revision = Number(response.current_revision || state.base_revision || 0)'
    base_new = '                    state.base_revision = Number(payload.base_revision || state.base_revision || 0)'
    if base_old not in text:
        raise RuntimeError("QField Changeset base revision marker missing")
    text = text.replace(base_old, base_new, 1)

    success_old = '                log("changeset applied revision=" + response.current_revision)\n                return'
    success_new = '                log("changeset applied revision=" + response.current_revision)\n                lastEditedStandard = ""\n                lastEditedFid = -1\n                pullDelta(manual)\n                return'
    if success_old not in text:
        raise RuntimeError("QField Changeset success marker missing")
    text = text.replace(success_old, success_new, 1)

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
        raise RuntimeError("QField Changeset 401 marker missing")
    text = text.replace(post_401_old, post_401_new, 1)

    auth_401_old = '''                if (!quiet && xhr.status === 401) {
                    toast("GeoFlow QField 인증 토큰이 만료되었거나 유효하지 않습니다")
                } else if (!quiet && xhr.status === 403) {'''
    auth_401_new = '''                if (xhr.status === 401) {
                    markSessionExpired(!quiet)
                } else if (!quiet && xhr.status === 403) {'''
    if auth_401_old not in text:
        raise RuntimeError("QField read 401 marker missing")
    text = text.replace(auth_401_old, auth_401_new, 1)

    init_old = f'''        updateUnsyncedCount(projectState())
        toast("GeoFlow Field {QFIELD_PLUGIN_RUNTIME_VERSION} 연결됨 · 서버 레이어 확인 중")
        scheduleRoaming(true)
        syncNow(false, false)'''
    init_new = f'''        updateUnsyncedCount(projectState())
        bindLayers()
        claimPendingSession(false, function(claimed) {{
            if (claimed || sessionAuthorized()) {{
                serverAuthRequired = false
                toast("GeoFlow Field {QFIELD_PLUGIN_RUNTIME_VERSION} 연결됨 · 증분 동기화 준비")
                syncNow(false, false)
            }} else {{
                serverAuthRequired = true
                toast("GeoFlow 로컬 프로젝트 열림 · 서버 사용은 GeoFlow 재인증 후 가능합니다")
            }}
        }})'''
    if init_old not in text:
        raise RuntimeError("QField initialize marker missing")
    text = text.replace(init_old, init_new, 1)

    required = (
        "import org.qfield.core",
        "QfFeatureModel",
        "function claimPendingSession",
        "function pullDelta",
        "qfield_claim_token",
        "qfield_session_claim_url",
        "qfield_delta_url",
        "qfield_snapshot_revision",
        "delta applied count=",
        "running: geoflowField.unsyncedCount > 0",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise RuntimeError("QField persistent render incomplete: " + ", ".join(missing))
    if "sessionRefreshTimer" in text or "refreshSession(" in text or "qfield_refresh_token" in text:
        raise RuntimeError("Autonomous QField refresh path must not exist")
    return text


def upgrade_qfield_bootstrap_zip(
    zip_path: Path,
    *,
    claim_token: str,
    session_claim_url: str,
    delta_url: str,
    access_expires_at_ms: int,
    snapshot_revision: int,
    schema_fingerprint: str,
    install_id: str,
) -> Path:
    source = Path(zip_path)
    temp = tempfile.NamedTemporaryFile(prefix="geoflow-qfield-persistent-", suffix=".zip", delete=False)
    output = Path(temp.name)
    temp.close()
    try:
        with zipfile.ZipFile(source, "r") as src, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename == f"{PROJECT_BASENAME}.qgs":
                    data = _inject_qgs_persistent_metadata(
                        data.decode("utf-8"),
                        claim_token=claim_token,
                        session_claim_url=session_claim_url,
                        delta_url=delta_url,
                        access_expires_at_ms=access_expires_at_ms,
                        snapshot_revision=snapshot_revision,
                        schema_fingerprint=schema_fingerprint,
                        install_id=install_id,
                    ).encode("utf-8")
                elif info.filename == f"{PROJECT_BASENAME}.qml":
                    data = _inject_qml_persistent_session(data.decode("utf-8")).encode("utf-8")
                elif info.filename == "README.txt":
                    data = (data.decode("utf-8") + (
                        f"- persistent protocol: {QFIELD_PERSISTENT_PROTOCOL_VERSION}\n"
                        f"- install id: {install_id}\n"
                        f"- snapshot revision: {snapshot_revision}\n"
                        "- access authorization never auto-renews.\n"
                        "- GeoFlow browser stages a 5-minute handoff; loaded QField project claims it.\n"
                        "- server-to-device synchronization uses revision Delta; automatic roaming is disabled.\n"
                    )).encode("utf-8")
                dst.writestr(info, data)
        os.replace(output, source)
        return source
    except Exception:
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        raise
