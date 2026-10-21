"""Project-scoped local raw_code recommendations (never server truth)."""
import json
from hashlib import sha256

from qgis.PyQt.QtCore import QSettings

from ..layers.model import layer_reference_bindings, reference_groups


def mapping_key(origin, project_id):
    server = sha256(str(origin).encode("utf-8")).hexdigest()[:24]
    return f"GeoFlowConnector/survey/{server}/{project_id}/raw_code_mapping"


def depth_create_key(origin, project_id):
    """Project-scoped facility codes which also create WTL_PIPE_PS."""
    return mapping_key(origin, project_id) + "/depth_create_targets"


def storage_code_key(origin, project_id):
    """Project-scoped facility identity -> physical field/code mapping."""
    return mapping_key(origin, project_id) + "/storage_codes"


def standard_mapping_key(origin, project_id):
    """Project-scoped standard code -> business/facility recommendation."""
    return mapping_key(origin, project_id) + "/standard_code_mapping"


def facility_identity(standard_name, label):
    """Stable business identity which deliberately does not contain a DB code."""
    return f"{str(standard_name or '').strip().upper()}::{str(label or '').strip().casefold()}"


def read_depth_create_targets(settings, key):
    try:
        value = json.loads(str(settings.value(key, "[]") or "[]"))
    except (TypeError, ValueError):
        return set()
    if not isinstance(value, list):
        return set()
    result = set()
    for row in value:
        if not isinstance(row, dict):
            continue
        standard = str(row.get("standard_name") or "").upper()
        code = str(row.get("ftr_cde") or "")
        if standard and code:
            result.add((standard, code))
    return result


def write_depth_create_targets(settings, key, targets):
    value = [
        {"standard_name": standard, "ftr_cde": code}
        for standard, code in sorted({
            (str(standard).upper(), str(code))
            for standard, code in targets if standard and code
        })
    ]
    settings.setValue(key, json.dumps(value, ensure_ascii=False, sort_keys=True))
    settings.sync()


def read_mappings(settings, key):
    try:
        value = json.loads(str(settings.value(key, "{}")))
    except (ValueError, TypeError):
        return {}
    if not isinstance(value, dict):
        return {}
    result = {}
    for raw, row in value.items():
        if not isinstance(row, dict):
            continue
        layer = str(row.get("layer") or row.get("standard_name") or "").upper()
        label = str(row.get("facility_label") or "")
        identity = str(row.get("facility_id") or "")
        result[str(raw)] = {
            "facility_id": identity,
            "facility_label": label,
            "layer": layer,
            # Kept only as a migration hint.  Creation code must never use it.
            "legacy_ftr_cde": str(row.get("legacy_ftr_cde") or row.get("ftr_cde") or ""),
        }
    return result


def write_mappings(settings, key, mappings):
    clean = {}
    for raw, row in mappings.items():
        if not str(raw).strip() or not isinstance(row, dict):
            continue
        layer = str(row.get("layer") or row.get("standard_name") or "").upper()
        label = str(row.get("facility_label") or "")
        if row.get("migration_unresolved"):
            clean[str(raw)] = {
                "facility_id": "", "facility_label": "", "layer": layer,
                "legacy_ftr_cde": str(row.get("legacy_ftr_cde") or label),
            }
            continue
        identity = str(row.get("facility_id") or facility_identity(layer, label))
        clean[str(raw)] = {
            "facility_id": identity,
            "facility_label": label,
            "layer": layer,
        }
    settings.setValue(key, json.dumps(clean, ensure_ascii=False, sort_keys=True))
    settings.sync()


def read_storage_codes(settings, key):
    try:
        value = json.loads(str(settings.value(key, "{}") or "{}"))
    except (ValueError, TypeError):
        return {}
    if not isinstance(value, dict):
        return {}
    result = {}
    for identity, row in value.items():
        if not isinstance(row, dict):
            continue
        result[str(identity)] = {
            "facility_id": str(row.get("facility_id") or identity),
            "facility_label": str(row.get("facility_label") or ""),
            "standard_name": str(row.get("standard_name") or "").upper(),
            "storage_field": str(row.get("storage_field") or "ftr_cde").casefold(),
            "storage_code": str(row.get("storage_code") or ""),
            "code_label": str(row.get("code_label") or ""),
        }
    return result


def write_storage_codes(settings, key, mappings):
    clean = {}
    for identity, row in mappings.items():
        if not identity or not isinstance(row, dict):
            continue
        clean[str(identity)] = {
            "facility_id": str(row.get("facility_id") or identity),
            "facility_label": str(row.get("facility_label") or ""),
            "standard_name": str(row.get("standard_name") or "").upper(),
            "storage_field": str(row.get("storage_field") or "ftr_cde").casefold(),
            "storage_code": str(row.get("storage_code") or ""),
            "code_label": str(row.get("code_label") or ""),
        }
    settings.setValue(key, json.dumps(clean, ensure_ascii=False, sort_keys=True))
    settings.sync()


def resolve_facility(catalog_rows, standard_name, value):
    """Resolve a legacy code/label only when it identifies exactly one option."""
    standard = str(standard_name or "").upper()
    text = str(value or "").strip()
    rows = [row for row in catalog_rows if str(row[2]).upper() == standard]
    code_matches = [row for row in rows if str(row[0]) == text]
    matches = code_matches or [row for row in rows if str(row[1]).casefold() == text.casefold()]
    if len(matches) != 1:
        return None
    code, label, layer = matches[0]
    return {
        "facility_id": facility_identity(layer, label or code),
        "facility_label": str(label or code),
        "layer": str(layer).upper(),
        "storage_code": str(code),
        "code_label": str(label or code),
    }


def ftr_catalog(catalog):
    """Return code/label/layer triples from explicit FTR_CDE bindings only."""
    groups = reference_groups(catalog or {})
    result, seen = [], set()
    standards = sorted({str(row.get("standard_name") or "").upper()
                        for row in (catalog or {}).get("bindings") or []})
    for standard in standards:
        for binding in layer_reference_bindings(catalog or {}, standard):
            if str(binding.get("field_name") or "").casefold() != "ftr_cde":
                continue
            for row in groups.get(str(binding.get("code_group_key") or ""), []):
                item = (str(row.get("code") or ""), str(row.get("label") or ""), standard)
                if item[0] and (item[0], item[2]) not in seen:
                    seen.add((item[0], item[2])); result.append(item)
    return sorted(result, key=lambda item: (item[2], item[0]))
