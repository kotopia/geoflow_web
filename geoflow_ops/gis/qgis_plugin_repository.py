from __future__ import annotations

import re


QGIS_PLUGIN_BUCKET = "geoflow-upload"
QGIS_PLUGIN_PREFIX = "qgis-plugins"
QGIS_PLUGIN_CHANNELS = frozenset({"test", "stable"})
QGIS_PLUGIN_TEST_PACKAGE = "geoflow_connector-0.7.6.zip"
QGIS_PLUGIN_PACKAGE_RE = re.compile(
    r"\Ageoflow_connector-[0-9]+\.[0-9]+\.[0-9]+\.zip\Z"
)


def repository_object_key(channel: str) -> str:
    normalized = str(channel or "").strip().lower()
    if normalized not in QGIS_PLUGIN_CHANNELS:
        raise ValueError("Unsupported QGIS plugin repository channel")
    return f"{QGIS_PLUGIN_PREFIX}/{normalized}/plugins.xml"


def package_object_key(filename: str) -> str:
    normalized = str(filename or "").strip()
    if not QGIS_PLUGIN_PACKAGE_RE.fullmatch(normalized):
        raise ValueError("Unsupported QGIS plugin package filename")
    return f"{QGIS_PLUGIN_PREFIX}/releases/{normalized}"
