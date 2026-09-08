from __future__ import annotations

import os
import tempfile
import zipfile
from pathlib import Path

from .qfield_package import PROJECT_BASENAME


_RESUME_MARKER = "    function log(message) {"
_RESUME_CONNECTION = r'''    Connections {
        target: Qt.application
        function onStateChanged() {
            if (Qt.application.state !== Qt.ApplicationActive) return
            if (!geoflowField.sessionAuthorized()) {
                geoflowField.claimPendingSession(false, function(ok) {
                    if (ok) geoflowField.syncNow(false, true)
                })
            } else {
                geoflowField.syncNow(false, false)
            }
        }
    }

'''
_ACTION_CONNECTION = r'''    Connections {
        target: iface
        function onExecuteAction(action) {
            let data = QfUrlUtils.getActionDetails(String(action))
            if (data.type !== "geoflow" || String(data.project) !== geoflowField.projectId ||
                String(data.server).replace(/\/+$/, "") !== geoflowField.serverUrl.replace(/\/+$/, "")) return
            geoflowField.claimPendingSession(false, function(ok) {
                if (ok) geoflowField.syncNow(false, false)
            })
        }
    }

'''
_SYNC_RUNNING_OLD = "        running: geoflowField.unsyncedCount > 0\n"
_SYNC_RUNNING_NEW = "        running: geoflowField.unsyncedCount > 0 && geoflowField.sessionAuthorized()\n"


_OWNER_RUNTIME = r'''    property var runtimeLease: null
    property bool runtimeActive: false
    function acquireRuntime() {
        let host = mainWindow.contentItem
        let lease = null
        for (let i = 0; i < host.children.length; i++) {
            if (host.children[i].objectName === "geoflowFieldRuntimeOwnerV1") {
                lease = host.children[i]
                break
            }
        }
        if (!lease) lease = Qt.createQmlObject(
            'import QtQuick; Item { objectName: "geoflowFieldRuntimeOwnerV1"; visible: false; property var owner: null }', host)
        runtimeLease = lease
        if (lease.owner && lease.owner !== geoflowField) return false
        lease.owner = geoflowField
        runtimeActive = true
        return true
    }
    function ownsRuntime() {
        return runtimeActive && runtimeLease && runtimeLease.owner === geoflowField
    }
    Timer {
        interval: 2000
        repeat: true
        running: !geoflowField.runtimeActive
        onTriggered: {
            if (geoflowField.acquireRuntime()) {
                geoflowField.log("runtime ownership acquired")
                iface.addItemToPluginsToolbar(syncButton)
                bootstrapTimer.restart()
            }
        }
    }

'''


def _single_owner_qml(text: str) -> str:
    if 'function ownsRuntime()' in text:
        return text
    text = text.replace('    function log(message) {', _OWNER_RUNTIME + '    function log(message) {', 1)
    # Disable external signals and entry points on duplicate plugin instances.
    text = text.replace('    Connections {\n', '    Connections {\n        enabled: geoflowField.runtimeActive\n')
    guarded = (
        'initializeProject()', 'reloadProjectConfig()', 'bindLayers()',
        'pollForLocalChanges(force)', 'syncNow(manual, acceptedEdit)',
        'postOutbox(payload, manual)', 'scheduleRoaming(force)',
        'authGet(path, callback, quiet)', 'pullDelta(manual)',
        'claimPendingSession(showMessage, callback)', 'manualSync()',
        'captureCreate(binding, fid)', 'captureAttribute(binding, fid, index, value)',
        'captureGeometry(binding, fid, geometry)', 'captureDelete(binding, fid)',
        'configure()', 'acceptConflictRecovery()',
    )
    for signature in guarded:
        marker = '    function ' + signature + ' {\n'
        if marker not in text:
            raise RuntimeError('QField owner guard marker missing: ' + signature)
        text = text.replace(marker, marker + '        if (!ownsRuntime()) return\n', 1)
    text = text.replace('        return Boolean(bearerToken && accessExpiresAtMs > Date.now())',
                        '        return Boolean(ownsRuntime() && bearerToken && accessExpiresAtMs > Date.now())')
    text = text.replace('        onTriggered: geoflowField.pollForLocalChanges(false)',
                        '        onTriggered: { if (geoflowField.runtimeActive) geoflowField.pollForLocalChanges(false) }')
    text = text.replace('        function onLoadProjectEnded(path, name) {\n',
        '        function onLoadProjectEnded(path, name) {\n            geoflowField.unbindLayers()\n            geoflowField.configReady = false\n            geoflowField.nextDeltaAtMs = 0\n            geoflowField.deltaSnapshotRequired = false\n', 1)
    text = text.replace('    Component.onCompleted: {\n',
        '    Component.onCompleted: {\n        if (!acquireRuntime()) { log("duplicate runtime suppressed"); return }\n', 1)
    text = text.replace('    Component.onDestruction: {\n',
        '    Component.onDestruction: {\n        if (runtimeLease && runtimeLease.owner === geoflowField) runtimeLease.owner = null\n        runtimeActive = false\n', 1)
    return text


def _finalize_qml(text: str) -> str:
    """Finalize foreground and retry behavior after persistent QML rendering."""

    if "target: Qt.application" not in text:
        if _RESUME_MARKER not in text:
            raise RuntimeError("QField resume injection marker missing")
        text = text.replace(_RESUME_MARKER, _RESUME_CONNECTION + _RESUME_MARKER, 1)

    if 'data.type !== "geoflow"' not in text:
        text = text.replace(_RESUME_MARKER, _ACTION_CONNECTION + _RESUME_MARKER, 1)

    if _SYNC_RUNNING_OLD in text:
        text = text.replace(_SYNC_RUNNING_OLD, _SYNC_RUNNING_NEW, 1)
    elif _SYNC_RUNNING_NEW not in text:
        raise RuntimeError("QField authenticated retry marker missing")

    required = (
        "target: Qt.application",
        "Qt.ApplicationActive",
        "claimPendingSession(false",
        "sessionAuthorized()",
        "running: geoflowField.unsyncedCount > 0 && geoflowField.sessionAuthorized()",
    )
    missing = [marker for marker in required if marker not in text]
    if missing:
        raise RuntimeError("QField resume runtime incomplete: " + ", ".join(missing))
    return _single_owner_qml(text)


def finalize_qfield_runtime_zip(zip_path: Path) -> Path:
    """Add foreground handoff claim and prevent expired-session retry traffic.

    Android MAIN restores the existing recent project on cold start. When
    QField is already alive, MAIN simply brings it forward; the loaded project
    then claims one handoff staged by GeoFlow. The retry timer remains disabled
    while server authorization is expired, so offline edits cannot poll the
    claim endpoint every three seconds.
    """

    source = Path(zip_path)
    temp = tempfile.NamedTemporaryFile(prefix="geoflow-qfield-finalize-", suffix=".zip", delete=False)
    output = Path(temp.name)
    temp.close()
    try:
        with zipfile.ZipFile(source, "r") as src, zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if info.filename == f"{PROJECT_BASENAME}.qml":
                    data = _finalize_qml(data.decode("utf-8")).encode("utf-8")
                dst.writestr(info, data)
        os.replace(output, source)
        return source
    except Exception:
        try:
            output.unlink(missing_ok=True)
        except OSError:
            pass
        raise
