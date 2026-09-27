"""Validation contract for persisted GIS photo annotation documents."""

from __future__ import annotations

import json
import math
import re


MAX_EDIT_DATA_BYTES = 256 * 1024
MAX_ANNOTATIONS = 200
MAX_POINTS = 2000
ANNOTATION_TYPES = frozenset({
    "line", "polyline", "freehand", "rectangle", "ellipse", "text", "icon",
})
_COLOR = re.compile(r"^#[0-9a-fA-F]{6}(?:[0-9a-fA-F]{2})?$")
_ID = re.compile(r"^[A-Za-z0-9_-]{1,100}$")
_ICON = re.compile(r"^[A-Za-z0-9_-]{1,80}$")


def _number(value, *, minimum=-100000, maximum=100000):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError("annotation number")
    if not minimum <= value <= maximum:
        raise ValueError("annotation number range")


def _point(value):
    if not isinstance(value, list) or len(value) != 2:
        raise ValueError("annotation point")
    _number(value[0]); _number(value[1])


def _style(row):
    for key in ("stroke", "color", "fill"):
        if key in row and (not isinstance(row[key], str) or not _COLOR.fullmatch(row[key])):
            raise ValueError("annotation color")
    if "stroke_width" in row:
        _number(row["stroke_width"], minimum=1, maximum=40)
    if "opacity" in row:
        _number(row["opacity"], minimum=0.05, maximum=1)
    if "rotation" in row:
        _number(row["rotation"], minimum=-3600, maximum=3600)
    if "z" in row:
        _number(row["z"], minimum=-10000, maximum=10000)


def _annotation(row, identifiers):
    if not isinstance(row, dict) or row.get("type") not in ANNOTATION_TYPES:
        raise ValueError("annotation type")
    identifier = row.get("id")
    if not isinstance(identifier, str) or not _ID.fullmatch(identifier) or identifier in identifiers:
        raise ValueError("annotation id")
    identifiers.add(identifier); _style(row)
    kind = row["type"]
    if kind == "line":
        _point(row.get("start")); _point(row.get("end"))
    elif kind in {"polyline", "freehand"}:
        points = row.get("points")
        if not isinstance(points, list) or not 2 <= len(points) <= MAX_POINTS:
            raise ValueError("annotation points")
        for point in points: _point(point)
    elif kind in {"rectangle", "ellipse"}:
        for key in ("x", "y", "width", "height"):
            _number(row.get(key), minimum=0 if key in {"width", "height"} else -100000)
    elif kind == "text":
        if not isinstance(row.get("text"), str) or not 1 <= len(row["text"]) <= 4000:
            raise ValueError("annotation text")
        for key in ("x", "y"): _number(row.get(key))
        _number(row.get("font_size", 28), minimum=8, maximum=160)
        if "bold" in row and not isinstance(row["bold"], bool): raise ValueError("annotation bold")
    elif kind == "icon":
        if not isinstance(row.get("icon"), str) or not _ICON.fullmatch(row["icon"]):
            raise ValueError("annotation icon")
        for key in ("x", "y"): _number(row.get(key))
        _number(row.get("size", 76), minimum=20, maximum=400)


def validate_edit_data(value):
    """Return a safe JSON object, preserving legacy raster edit documents."""
    if not isinstance(value, dict):
        raise ValueError("edit data object")
    try:
        encoded = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    except (TypeError, ValueError):
        raise ValueError("edit data json") from None
    if len(encoded.encode("utf-8")) > MAX_EDIT_DATA_BYTES:
        raise ValueError("edit data size")
    if not value:
        return value
    version, format_name = value.get("version"), value.get("format")
    if version == 1 and format_name == "raster-png":
        return value
    # Connector 1.3.3 emitted raster-only version 2 documents. Keep them readable.
    if version == 2 and format_name == "raster-jpeg":
        return value
    if version != 2 or format_name != "annotation-json":
        raise ValueError("edit data version")
    canvas, rows = value.get("canvas"), value.get("annotations")
    if not isinstance(canvas, dict) or not isinstance(rows, list) or len(rows) > MAX_ANNOTATIONS:
        raise ValueError("annotation document")
    for key in ("width", "height"):
        _number(canvas.get(key), minimum=1, maximum=20000)
    identifiers = set()
    for row in rows: _annotation(row, identifiers)
    if "render" in value and not isinstance(value["render"], dict):
        raise ValueError("annotation render")
    return value

