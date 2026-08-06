from __future__ import annotations

import json
from collections.abc import Mapping


def get_optional_env_text(
    environ: Mapping[str, str],
    name: str,
) -> str | None:
    raw = environ.get(name)
    if raw is None:
        return None
    value = str(raw).strip()
    return value or None


def get_optional_env_int(
    environ: Mapping[str, str],
    name: str,
    *,
    minimum: int,
    maximum: int,
) -> int | None:
    raw = get_optional_env_text(environ, name)
    if raw is None:
        return None
    try:
        value = int(raw, 10)
    except ValueError:
        raise RuntimeError(f"Invalid integer environment variable: {name}") from None
    if not minimum <= value <= maximum:
        raise RuntimeError(f"Out-of-range integer environment variable: {name}")
    return value


def get_optional_env_text_mapping(
    environ: Mapping[str, str],
    name: str,
) -> dict[str, str]:
    raw = get_optional_env_text(environ, name)
    if raw is None:
        return {}
    try:
        decoded = json.loads(raw)
    except (TypeError, ValueError):
        raise RuntimeError(f"Invalid JSON environment variable: {name}") from None
    if not isinstance(decoded, dict) or not decoded:
        raise RuntimeError(f"Invalid mapping environment variable: {name}")

    result: dict[str, str] = {}
    for key, value in decoded.items():
        if not isinstance(key, str) or not key.strip():
            raise RuntimeError(f"Invalid mapping environment variable: {name}")
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(f"Invalid mapping environment variable: {name}")
        result[key.strip()] = value.strip()
    return result
