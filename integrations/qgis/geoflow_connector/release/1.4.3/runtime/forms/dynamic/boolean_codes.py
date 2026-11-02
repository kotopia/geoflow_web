"""Mapping helpers for code-backed boolean Dynamic Form fields."""
from __future__ import annotations


_BOOLEAN_STORAGE_TYPES = {"bool", "boolean", "pg_catalog.bool"}
_TEXT_STORAGE_TYPES = {
    "char", "character", "character varying", "varchar", "text", "bpchar",
    "pg_catalog.varchar", "pg_catalog.text", "pg_catalog.bpchar",
}


def _text(value):
    return str(value or "").strip().casefold()


def _storage_type(field):
    storage = field.get("storage") if isinstance(field.get("storage"), dict) else {}
    for source in (storage, field):
        for key in (
            "data_type", "storage_data_type", "udt_name", "storage_udt_name",
            "column_type", "physical_data_type",
        ):
            value = _text(source.get(key))
            if value:
                return value
    return ""


def _physical_names(field):
    storage = field.get("storage") if isinstance(field.get("storage"), dict) else {}
    return {
        _text(field.get(key))
        for key in ("name", "field_name", "field_identifier", "physical_name")
    } | {_text(storage.get("key"))}


def boolean_code_values(field):
    """Return ordered (false, true) codes only for a varchar code checkbox.

    Explicit boolean storage always wins.  Text storage is handled generically;
    ``status`` is the conservative compatibility fallback for the current v3
    definition, whose storage type is not guaranteed to be included in every
    response.
    """
    kind = _text(field.get("widget_type") or field.get("semantic_data_type"))
    codes = list(field.get("reference_codes") or [])
    if kind != "boolean" or len(codes) != 2:
        return None
    values = tuple(str(row.get("value") or "") for row in codes)
    if not all(values):
        return None
    storage_type = _storage_type(field)
    if storage_type in _BOOLEAN_STORAGE_TYPES:
        return None
    if storage_type in _TEXT_STORAGE_TYPES or "status" in _physical_names(field):
        return values
    return None


def canonical_boolean_code(field, value):
    """Convert a checkbox bool to its central code without inventing strings."""
    codes = boolean_code_values(field)
    if codes is None:
        return value
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return codes[1] if value else codes[0]
    return str(value)
