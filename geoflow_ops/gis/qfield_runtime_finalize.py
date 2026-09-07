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
            if (geoflowField.serverAuthRequired) {
                geoflowField.claimPendingSession(false, function(ok) {
                    if (ok) geoflowField.syncNow(false, true)
                })
            } else if (geoflowField.sessionAuthorized()) {
                geoflowField.syncNow(false, false)
            }
        }
    }

'''


def finalize_qfield_runtime_zip(zip_path: Path) -> Path:
    """Add foreground-resume claim/delta behavior after persistent rendering.

    Android MAIN launch restores the existing project on cold start. When QField
    is already alive, MAIN simply brings it to the foreground; this connection
    gives the already-loaded project plugin one chance to claim the handoff
    staged by GeoFlow. It also performs one Delta check per foreground resume,
    never a periodic poll.
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
                    text = data.decode("utf-8")
                    if "target: Qt.application" not in text:
                        if _RESUME_MARKER not in text:
                            raise RuntimeError("QField resume injection marker missing")
                        text = text.replace(_RESUME_MARKER, _RESUME_CONNECTION + _RESUME_MARKER, 1)
                    required = (
                        "target: Qt.application",
                        "Qt.ApplicationActive",
                        "claimPendingSession(false",
                        "sessionAuthorized()",
                    )
                    missing = [marker for marker in required if marker not in text]
                    if missing:
                        raise RuntimeError("QField resume runtime incomplete: " + ", ".join(missing))
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
