"""Static and QGIS-expression audit for the bundled default QML files."""
from __future__ import annotations

import os
import re
import sqlite3
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from qgis.core import QgsApplication, QgsExpression, QgsVectorLayer


PLUGIN_DIR = Path(__file__).resolve().parents[1]
if str(PLUGIN_DIR.parent) not in sys.path:
    sys.path.insert(0, str(PLUGIN_DIR.parent))

from geoflow_connector.layers.default_style import (  # noqa: E402
    DEFAULT_STYLE_MAP,
    STYLE_DIRECTORY,
)


RISK_TAGS = (
    "customproperties",
    "editform",
    "editorlayout",
    "layerDependencies",
    "referencedLayers",
    "fieldConfiguration",
    "constraints",
    "aliases",
)
PATH_RE = re.compile(r"[A-Za-z]:[\\/]")


def find_sources() -> dict[str, Path]:
    root = Path(os.environ["APPDATA"]) / "QGIS" / "QGIS4" / "GeoFlowConnector" / "projects"
    result = {}
    for package in sorted(root.rglob("geoflow-*.gpkg"), key=lambda p: p.stat().st_mtime, reverse=True):
        if "_recovery_quarantine_" in str(package):
            continue
        try:
            with sqlite3.connect(f"file:{package.as_posix()}?mode=ro", uri=True) as connection:
                tables = {
                    str(row[0]).lower()
                    for row in connection.execute(
                        "SELECT table_name FROM gpkg_contents WHERE data_type='features'"
                    )
                }
        except (OSError, sqlite3.Error):
            continue
        for canonical in DEFAULT_STYLE_MAP:
            if canonical in tables and canonical not in result:
                result[canonical] = package
        if len(result) == len(DEFAULT_STYLE_MAP):
            break
    return result


app = QgsApplication([], False)
app.initQgis()
failures = []
warnings = []
try:
    sources = find_sources()
    for canonical, filename in DEFAULT_STYLE_MAP.items():
        path = STYLE_DIRECTORY / filename
        try:
            root = ET.parse(path).getroot()
        except (OSError, ET.ParseError) as exc:
            failures.append(f"{canonical}: XML {exc}")
            print(f"FAIL {canonical}: XML {exc}")
            continue

        tags = {element.tag for element in root.iter()}
        renderer = "renderer-v2" in tags or "renderer" in tags
        labeling = "labeling" in tags
        risks = [tag for tag in RISK_TAGS if tag in tags]
        paths = []
        expressions = []
        for element in root.iter():
            for key, value in element.attrib.items():
                if PATH_RE.search(value or ""):
                    paths.append(value)
                if key in {"filter", "fieldName", "expression"} and value and value != "ELSE":
                    expressions.append(value)

        bad_expressions = []
        missing_fields = set()
        package = sources.get(canonical)
        layer = None
        field_names = set()
        if package is not None:
            layer = QgsVectorLayer(f"{package}|layername={canonical}", canonical, "ogr")
            # QGIS field lookup is case-insensitive for unquoted identifiers.
            field_names = {field.name().lower() for field in layer.fields()}
        for source in expressions:
            expression = QgsExpression(source)
            if expression.hasParserError():
                bad_expressions.append(source)
                continue
            if layer is not None:
                missing_fields.update(
                    name for name in expression.referencedColumns()
                    if name.lower() not in field_names
                )

        checks = {
            "xml": root.tag == "qgis",
            "renderer": renderer,
            "labeling": labeling,
            "expressions": not bad_expressions,
            "runtime_source": layer is not None and layer.isValid(),
        }
        failed = [name for name, passed in checks.items() if not passed]
        if failed:
            failures.append(f"{canonical}: {', '.join(failed)}")
            print(
                f"FAIL {canonical}: {', '.join(failed)} "
                f"parser_errors={len(bad_expressions)} missing={sorted(missing_fields)}"
            )
        else:
            if missing_fields:
                warnings.append(f"{canonical}: {sorted(missing_fields)}")
            print(
                f"PASS {canonical}: version={root.get('version', '')} "
                f"expressions={len(expressions)} risk={','.join(risks) or '-'} "
                f"absolute_paths={len(paths)} "
                f"missing_field_refs={sorted(missing_fields)}"
            )

    if failures:
        raise AssertionError("; ".join(failures))
    if warnings:
        print("WARN current-schema field references: " + "; ".join(warnings))
finally:
    app.exitQgis()
