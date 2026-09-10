from __future__ import annotations

from botocore.exceptions import BotoCoreError, ClientError
from django.http import Http404, StreamingHttpResponse
from django.views.decorators.http import require_GET

from geoflow_ops.services.s3_service import get_s3_client

from .qgis_plugin_repository import (
    QGIS_PLUGIN_BUCKET,
    package_object_key,
    repository_object_key,
)


def _private_plugin_object(key: str):
    try:
        return get_s3_client().get_object(Bucket=QGIS_PLUGIN_BUCKET, Key=key)
    except (BotoCoreError, ClientError):
        raise Http404("QGIS plugin artifact is unavailable") from None


def _stream_body(body, *, chunk_size=64 * 1024):
    try:
        while True:
            chunk = body.read(chunk_size)
            if not chunk:
                break
            yield chunk
    finally:
        body.close()


@require_GET
def qgis_plugin_repository_xml(request, channel):
    try:
        key = repository_object_key(channel)
    except ValueError:
        raise Http404("Unknown QGIS plugin repository") from None
    result = _private_plugin_object(key)
    response = StreamingHttpResponse(
        _stream_body(result["Body"]), content_type="application/xml; charset=utf-8"
    )
    if result.get("ContentLength") is not None:
        response["Content-Length"] = str(result["ContentLength"])
    response["Cache-Control"] = "no-cache, no-store, must-revalidate"
    response["X-Content-Type-Options"] = "nosniff"
    return response


@require_GET
def qgis_plugin_package(request, filename):
    try:
        key = package_object_key(filename)
    except ValueError:
        raise Http404("Unknown QGIS plugin package") from None
    result = _private_plugin_object(key)
    response = StreamingHttpResponse(
        _stream_body(result["Body"]), content_type="application/zip"
    )
    if result.get("ContentLength") is not None:
        response["Content-Length"] = str(result["ContentLength"])
    response["Content-Disposition"] = f'attachment; filename="{filename}"'
    response["Cache-Control"] = "public, max-age=31536000, immutable"
    response["X-Content-Type-Options"] = "nosniff"
    return response
