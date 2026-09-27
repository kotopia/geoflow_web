"""Normalize GIS field photos and preserve safe image metadata before upload."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import io
import json

MAX_PHOTO_BYTES = 500 * 1024
LONG_EDGE = 1920
START_QUALITY = 82
MIN_QUALITY = 46


@dataclass(frozen=True)
class NormalizedPhoto:
    data: bytes
    mime_type: str
    image_metadata: dict
    captured_at: str | None = None


def _json_value(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", "replace")[:4000]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (tuple, list)):
        return [_json_value(item) for item in value]
    if isinstance(value, dict):
        return {str(key): _json_value(item) for key, item in value.items()}
    try:
        return float(value)
    except (TypeError, ValueError, OverflowError):
        return str(value)[:4000]


def _gps_decimal(values, reference):
    if not values or len(values) < 3:
        return None
    result = float(values[0]) + float(values[1]) / 60 + float(values[2]) / 3600
    return -result if str(reference).upper() in {"S", "W"} else result


def _pillow_load(path):
    """Use Pillow when available; QGIS builds without it use the Qt fallback."""
    try:
        from PIL import ExifTags, Image, ImageOps
    except ImportError:
        return None
    source = Image.open(path)
    exif = source.getexif()
    named = {}
    # Pillow exposes TIFF/IFD0 separately from the camera EXIF sub-IFD.  Read
    # both so normal phone fields such as DateTimeOriginal and LensModel are
    # retained even though the normalized JPEG deliberately carries no EXIF.
    for values in (exif, _safe_ifd(exif, 0x8769)):
        for key, value in values.items():
            name = ExifTags.TAGS.get(key, str(key))
            if name not in {"GPSInfo", "ExifOffset"}:
                named[name] = _json_value(value)
    gps = {}
    for key, value in _safe_ifd(exif, 0x8825).items():
        gps[ExifTags.GPSTAGS.get(key, str(key))] = _json_value(value)
    source_orientation = int(exif.get(0x0112, 1) or 1)
    rotation = {3: 180, 5: 90, 6: 90, 7: 270, 8: 270}.get(source_orientation, 0)
    mirrored = source_orientation in {2, 4, 5, 7}
    original_size = source.size
    image = ImageOps.exif_transpose(source).convert("RGB")
    latitude = _gps_decimal(gps.get("GPSLatitude"), gps.get("GPSLatitudeRef"))
    longitude = _gps_decimal(gps.get("GPSLongitude"), gps.get("GPSLongitudeRef"))
    altitude = gps.get("GPSAltitude")
    if altitude is not None:
        altitude = float(altitude) * (-1 if int(gps.get("GPSAltitudeRef") or 0) == 1 else 1)
    captured = named.get("DateTimeOriginal") or named.get("DateTimeDigitized") or named.get("DateTime")
    captured = _aware_exif_time(captured, named.get("OffsetTimeOriginal")
                                or named.get("OffsetTimeDigitized") or named.get("OffsetTime"))
    metadata = {
        "exif": named,
        "gps": {key: value for key, value in {
            "latitude": latitude, "longitude": longitude, "altitude": altitude,
            "image_direction": gps.get("GPSImgDirection"),
            "destination_bearing": gps.get("GPSDestBearing"),
        }.items() if value is not None},
        "source_orientation": source_orientation,
        "original_width": original_size[0], "original_height": original_size[1],
        "normalization": {"rotation_applied": rotation, "mirrored": mirrored,
                          "normalized_orientation": 1},
    }
    return image, metadata, str(captured or "")


def _safe_ifd(exif, tag):
    try:
        value = exif.get_ifd(tag)
        return value if hasattr(value, "items") else {}
    except (KeyError, TypeError, ValueError, AttributeError):
        return {}


def _aware_exif_time(value, offset):
    """Convert EXIF local time only when the camera supplied a UTC offset."""
    value, offset = str(value or "").strip(), str(offset or "").strip()
    if not value or not re_full_offset(offset):
        return value
    try:
        local = datetime.strptime(value[:19], "%Y:%m:%d %H:%M:%S")
        return local.isoformat() + offset
    except ValueError:
        return value


def re_full_offset(value):
    if len(value) != 6 or value[0] not in "+-" or value[3] != ":":
        return False
    return value[1:3].isdigit() and value[4:6].isdigit()


def _encode_pillow(image):
    working = image.copy()
    if max(working.size) > LONG_EDGE:
        scale = LONG_EDGE / max(working.size)
        working.thumbnail((round(working.width * scale), round(working.height * scale)))
    while True:
        for quality in range(START_QUALITY, MIN_QUALITY - 1, -6):
            output = io.BytesIO()
            working.save(output, "JPEG", quality=quality, optimize=True, progressive=True)
            if output.tell() <= MAX_PHOTO_BYTES:
                return output.getvalue(), working.size, quality
        if max(working.size) <= 640:
            raise ValueError("사진을 500KB 이하로 정규화할 수 없습니다.")
        working = working.resize((max(1, round(working.width * .85)),
                                  max(1, round(working.height * .85))))


def encode_qimage(image, limit=MAX_PHOTO_BYTES):
    """Encode an edited opaque image as bounded JPEG, reducing quality then pixels."""
    from qgis.PyQt.QtCore import QByteArray, QBuffer, QIODevice, Qt
    from qgis.PyQt.QtGui import QImage
    working = image.convertToFormat(QImage.Format.Format_RGB32)
    if max(working.width(), working.height()) > LONG_EDGE:
        working = working.scaled(LONG_EDGE, LONG_EDGE, Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)
    while True:
        for quality in range(START_QUALITY, MIN_QUALITY - 1, -6):
            data = QByteArray()
            buffer = QBuffer(data)
            mode = getattr(getattr(QIODevice, "OpenModeFlag", QIODevice), "WriteOnly")
            buffer.open(mode)
            if not working.save(buffer, "JPEG", quality):
                raise ValueError("JPEG 편집본을 만들 수 없습니다.")
            value = bytes(data)
            if len(value) <= limit:
                return value, working.width(), working.height(), quality
        if max(working.width(), working.height()) <= 640:
            raise ValueError("편집 사진을 500KB 이하로 만들 수 없습니다.")
        working = working.scaled(max(1, round(working.width() * .85)),
                                 max(1, round(working.height() * .85)),
                                 Qt.AspectRatioMode.KeepAspectRatio,
                                 Qt.TransformationMode.SmoothTransformation)


def normalize_photo(path):
    loaded = _pillow_load(path)
    if loaded is not None:
        image, metadata, captured = loaded
        data, size, quality = _encode_pillow(image)
        metadata.update({"normalized_width": size[0], "normalized_height": size[1],
                         "normalization": {**metadata["normalization"],
                                           "format": "JPEG", "quality": quality,
                                           "target_bytes": MAX_PHOTO_BYTES}})
    else:
        from qgis.PyQt.QtGui import QImageReader
        reader = QImageReader(path)
        reader.setAutoTransform(True)
        image = reader.read()
        if image.isNull():
            raise ValueError("사진 파일을 읽을 수 없습니다.")
        data, width, height, quality = encode_qimage(image)
        metadata = {
            "exif": {key: reader.text(key) for key in reader.textKeys()}, "gps": {},
            "source_orientation": None, "original_width": reader.size().width(),
            "original_height": reader.size().height(), "normalized_width": width,
            "normalized_height": height, "normalization": {
                "rotation_applied": None, "mirrored": None, "normalized_orientation": 1,
                "format": "JPEG", "quality": quality, "target_bytes": MAX_PHOTO_BYTES,
            },
        }
        captured = ""
    # Enforce a bounded JSON contract even for unusual vendor EXIF blocks.
    if len(json.dumps(metadata, ensure_ascii=False, default=str).encode("utf-8")) > 60_000:
        metadata["exif"] = {key: metadata["exif"].get(key) for key in (
            "DateTimeOriginal", "DateTimeDigitized", "DateTime", "Make", "Model",
            "LensModel", "FocalLength", "FNumber", "ExposureTime", "ISOSpeedRatings",
            "PixelXDimension", "PixelYDimension", "Software", "ColorSpace")
            if metadata["exif"].get(key) is not None}
    if len(json.dumps(metadata, ensure_ascii=False, default=str).encode("utf-8")) > 60_000:
        metadata["exif"] = {
            key: (value[:512] if isinstance(value, str) else value)
            for key, value in metadata["exif"].items()
        }
    captured_at = None
    try:
        # Only expose an aware timestamp. Naive EXIF time remains preserved in image_metadata.
        parsed = datetime.fromisoformat(captured)
        captured_at = parsed.isoformat() if parsed.tzinfo is not None else None
    except (TypeError, ValueError):
        pass
    return NormalizedPhoto(data, "image/jpeg", metadata, captured_at)
