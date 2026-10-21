from __future__ import annotations

import xml.etree.ElementTree as ET
from urllib.parse import urlsplit

from botocore.exceptions import BotoCoreError, ClientError
from django.http import Http404, HttpResponseRedirect, StreamingHttpResponse
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
def qgis_plugin_repository_xml(request, channel="stable"):
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
def qgis_plugin_package(request, filename, channel="test"):
    try:
        key = package_object_key(filename, channel)
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


@require_GET
def qgis_plugin_stable_download(request):
    """Follow the current stable index without embedding a version in the Web UI."""
    result = _private_plugin_object(repository_object_key('stable'))
    try:
        data = result['Body'].read(65537)
    finally:
        result['Body'].close()
    try:
        if len(data) > 65536:
            raise ValueError('index too large')
        plugin = ET.fromstring(data).find('pyqgis_plugin')
        url = plugin.findtext('download_url')
        parsed = urlsplit(url)
        filename = parsed.path.rsplit('/',1)[-1]
        package_object_key(filename,'stable')
        if (parsed.scheme != 'https' or parsed.netloc != 'geoflow.co.kr'
                or parsed.path != '/gis/qgis/plugins/packages/'+filename or parsed.query or parsed.fragment):
            raise ValueError('invalid stable URL')
    except (ValueError, TypeError, AttributeError, ET.ParseError):
        raise Http404('Stable QGIS package is unavailable') from None
    response = HttpResponseRedirect(url)
    response['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    return response
