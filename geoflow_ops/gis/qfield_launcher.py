"""Code-only app plugin distribution; no project data or credentials."""
import io
import zipfile
from pathlib import Path
from django.conf import settings
from django.http import FileResponse
from django.views.decorators.http import require_GET
from .qfield_package import _render_qfield_plugin
from .qfield_persistent import _inject_qml_persistent_session
from .qfield_runtime_finalize import _finalize_qml

@require_GET
def launcher_download(request):
    root = Path(settings.BASE_DIR) / "integrations/qfield/launcher"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("main.qml", "metadata.txt"):
            archive.writestr(name, (root / name).read_bytes())
        archive.writestr("field-runtime.qml", _finalize_qml(_inject_qml_persistent_session(_render_qfield_plugin(Path(settings.BASE_DIR) / "integrations/qfield/geoflow-field.qml"))))
    buffer.seek(0)
    response = FileResponse(buffer, as_attachment=True, filename="geoflow-launcher.zip")
    response["Cache-Control"] = "no-store"
    return response
