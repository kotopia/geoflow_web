"""Code-only app plugin distribution; no project data or credentials."""
import io
import zipfile
from pathlib import Path
from django.conf import settings
from django.http import FileResponse
from django.views.decorators.http import require_GET

@require_GET
def launcher_download(request):
    root = Path(settings.BASE_DIR) / "integrations/qfield/launcher"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name in ("main.qml", "metadata.txt"):
            archive.writestr(name, (root / name).read_bytes())
    buffer.seek(0)
    response = FileResponse(buffer, as_attachment=True, filename="geoflow-launcher.zip")
    response["Cache-Control"] = "no-store"
    return response
