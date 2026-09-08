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
    return text


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
