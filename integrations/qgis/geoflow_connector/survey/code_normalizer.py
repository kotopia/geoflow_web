"""Project-scoped optional Survey raw-code normalization rules."""
from __future__ import annotations

import json
from qgis.PyQt.QtCore import QSettings
from .code_mapping import mapping_key

# Initial project template. A saved rule list is authoritative, so deleted or
# disabled defaults do not reappear.
DEFAULT_RULES = (
    ("h", "H"), ("H", "H"),
    ("d", "DO"), ("D", "DO"), ("do", "DO"), ("Do", "DO"),
    ("j", "J"), ("J", "J"), ("je", "J"), ("JE", "J"),
)


def read_code_rule_rows(settings, key):
    """Read ordered L2-aware rules while accepting every legacy format."""
    raw_value = settings.value(key, None)
    if raw_value in (None, ""):
        defaults = {
            str(raw).strip().upper(): str(code).strip().upper()
            for raw, code in DEFAULT_RULES
        }
        return [{"business_type": "", "raw_code": raw,
                 "survey_code": code, "enabled": True}
                for raw, code in defaults.items()]
    try:
        value = json.loads(str(raw_value))
    except (TypeError, ValueError):
        value = {}
    if isinstance(value, dict) and "rules" not in value:
        legacy = {
            str(raw).strip().upper(): str(code).strip().upper()
            for raw, code in value.items()
            if str(raw).strip() and str(code).strip()
        }
        return [{"business_type": "", "raw_code": raw,
                 "survey_code": code, "enabled": True}
                for raw, code in legacy.items()]
    rows = value.get("rules", []) if isinstance(value, dict) else []
    result = {}
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("raw_code") or "").strip().upper()
        code = str(row.get("survey_code") or "").strip().upper()
        if raw and code:
            business = str(row.get("business_type") or "").strip()
            result[(business, raw)] = {
                "business_type": business,
                "raw_code": raw,
                "survey_code": code,
                "enabled": bool(row.get("enabled", True)),
            }
    return list(result.values())


def write_code_rule_rows(settings, key, rows):
    clean = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        raw = str(row.get("raw_code") or "").strip().upper()
        code = str(row.get("survey_code") or "").strip().upper()
        if raw and code:
            clean.append({
                "business_type": str(row.get("business_type") or "").strip(),
                "raw_code": raw,
                "survey_code": code,
                "enabled": bool(row.get("enabled", True)),
            })
    clean.sort(key=lambda row: (
        row["business_type"].casefold(), row["raw_code"], row["survey_code"]
    ))
    settings.setValue(
        key, json.dumps({"version": 3, "rules": clean}, ensure_ascii=False)
    )
    settings.sync()


def normalization_key(origin, project_id):
    return mapping_key(origin, project_id) + "/normalization_aliases"


def read_code_rules(settings, key):
    result = {}
    for row in read_code_rule_rows(settings, key):
        # Compatibility view for callers which pre-date L2-aware rules.
        result.setdefault(row["raw_code"], {
            "survey_code": row["survey_code"],
            "enabled": row["enabled"],
            "business_type": row["business_type"],
        })
    return result


def write_code_rules(settings, key, rules):
    write_code_rule_rows(settings, key, [
        {"business_type": row.get("business_type", ""),
         "raw_code": raw, "survey_code": row["survey_code"],
         "enabled": bool(row.get("enabled", True))}
        for raw, row in rules.items() if raw and row.get("survey_code")
    ])


def read_code_aliases(settings, key):
    return {raw: row["survey_code"] for raw, row in read_code_rules(settings, key).items()
            if row.get("enabled")}


def write_code_aliases(settings, key, aliases):
    write_code_rules(settings, key, {
        str(raw).strip(): {"survey_code": str(code).strip(), "enabled": True}
        for raw, code in aliases.items() if str(raw).strip() and str(code).strip()
    })


def normalize_raw_code(project_id, raw_code, *, settings=None, origin="",
                       business_type=""):
    """Uppercase a raw code, then apply an optional exact L2-aware rule."""
    raw = str(raw_code or "").strip()
    if not raw:
        return None
    upper = raw.upper()
    business = str(business_type or "").strip()
    rows = read_code_rule_rows(
        settings or QSettings(), normalization_key(origin, project_id)
    )
    candidates = [row for row in rows if row["enabled"] and row["raw_code"] == upper]
    rule = next((row for row in candidates
                 if business and row["business_type"] == business), None)
    rule = rule or next((row for row in candidates if not row["business_type"]), None)
    return rule["survey_code"] if rule else upper


def standard_code_role(code):
    return {"H": "ELEVATION_REFERENCE", "DO": "ROAD", "J": "FACILITY",
            "T": "DEPTH"}.get(str(code or "").strip().upper(), "FACILITY")
