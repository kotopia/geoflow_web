from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable


def extract_gpkg_wkb(blob: bytes | memoryview | None) -> bytes | None:
    if blob is None:
        return None
    raw = bytes(blob)
    if len(raw) < 8 or raw[:2] != b"GP":
        raise ValueError("invalid GeoPackage geometry blob")
    flags = raw[3]
    envelope_code = (flags >> 1) & 0x07
    envelope_sizes = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}
    if envelope_code not in envelope_sizes:
        raise ValueError("unsupported GeoPackage geometry envelope")
    offset = 8 + envelope_sizes[envelope_code]
    if len(raw) <= offset:
        return None
    return raw[offset:]


def _json_safe(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, (bytes, bytearray, memoryview)):
        return {"__bytes__": bytes(value).hex()}
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    return str(value)


def content_hash(
    attributes: dict[str, Any],
    geometry_wkb: bytes | memoryview | None,
    editable_names: Iterable[str],
) -> str:
    names = sorted({str(name) for name in editable_names})
    payload = {
        "attributes": {name: _json_safe(attributes.get(name)) for name in names},
        "geometry_wkb": bytes(geometry_wkb).hex() if geometry_wkb is not None else None,
    }
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()
