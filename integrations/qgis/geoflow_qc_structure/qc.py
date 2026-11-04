"""Pure value validation and structured QC findings."""
from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from uuid import UUID


@dataclass(frozen=True)
class Finding:
    rule_id: str
    rule_name: str
    severity: str
    blocks_structure: bool
    layer: str
    feature_id: int
    field: str | None
    message: str
    geometry: object
    measured: object
    expected: object
    status: str = "OPEN"


INT_BITS = {"SMALLINT": 16, "INTEGER": 32, "BIGINT": 64}


def numeric(value):
    if isinstance(value, bool) or not isinstance(value, (int, float, Decimal)):
        raise ValueError("Numeric value required")
    n = Decimal(str(value))
    if not n.is_finite():
        raise ValueError("Finite numeric value required")
    return n


def type_valid(value, kind):
    try:
        if kind in INT_BITS:
            bound = 2 ** (INT_BITS[kind]-1)
            return type(value) is int and -bound <= value < bound
        if kind in {"NUMERIC", "DECIMAL", "REAL", "DOUBLE"}:
            numeric(value)
            return True
        if kind in {"CHAR", "VARCHAR", "TEXT"}:
            return isinstance(value, str)
        if kind == "BOOLEAN":
            return type(value) is bool
        if kind == "UUID":
            UUID(str(value))
            return True
        if kind == "DATE":
            return type(value) is date
        if kind in {"DATETIME", "TIMESTAMP"}:
            return isinstance(value, datetime)
        return kind == "GEOMETRY" and value is not None
    except (ValueError, InvalidOperation):
        return False


def number_digits(value):
    n = numeric(value)
    _, digits, exponent = n.as_tuple()
    while exponent < 0 and digits[-1:] == (0,):
        exponent += 1
        digits = digits[:-1]
    return (max(0, n.adjusted()+1) if n else 0, max(0, -exponent) if n else 0)


def check(kind, value, geometry, params, spatial, duplicates):
    if kind == "REQUIRED":
        return value is not None and (not isinstance(value, str) or bool(value.strip()))
    if kind == "NULL_CHECK":
        return value is not None
    if kind == "GEOMETRY_EXISTS":
        return spatial.exists(geometry)
    if kind == "GEOMETRY_VALID":
        return spatial.valid(geometry)
    if kind == "GEOMETRY_TYPE":
        return spatial.geometry_type(geometry) in params["types"] and (
            not params.get("crs") or spatial.crs.authid() == params["crs"])
    if kind == "DUPLICATE":
        return value is None or duplicates[repr(value)] <= 1
    if kind in {"REFERENCE_EXISTS", "START_REFERENCE", "END_REFERENCE"}:
        return spatial.lookup(geometry, params, kind, existence=True)
    if value is None:
        return True
    if kind == "TYPE_CHECK":
        return type_valid(value, params["data_type"])
    if kind == "LENGTH_CHECK":
        return isinstance(value, str) and len(value) <= params["length"]
    if kind == "PRECISION_CHECK":
        return number_digits(value)[0] <= params["precision"] - params.get("scale", 0)
    if kind == "SCALE_CHECK":
        return number_digits(value)[1] <= params["scale"]
    if kind == "RANGE_CHECK":
        return params["min"] <= value <= params["max"]
    if kind == "REFERENCE_CODE_VALID":
        return value in params["codes"]
    raise ValueError(f"Unknown QC rule: {kind}")


def run_qc(layer, rows, rules, spatial, phase, selected=None):
    findings = []
    for key, rule in rules.items():
        if rule.get("phase", "PRE") not in {phase, "BOTH"}:
            continue
        field, kind = rule.get("field"), rule["type"]
        params = rule.get("params", {})
        def measure(row):
            attrs, geom = row[1:]
            return attrs.get(field) if field else (spatial.geometry_key(geom) if kind == "DUPLICATE" else None)
        counts = Counter(repr(measure(row)) for row in rows) if kind == "DUPLICATE" else {}
        for fid, attrs, geom in rows:
            if selected is not None and fid not in selected:
                continue
            value = measure((fid, attrs, geom))
            try:
                if field and field not in attrs:
                    raise ValueError("필드 없음")
                if check(kind, value, geom, params, spatial, counts):
                    continue
                message = rule.get("message", f"{kind} 검사 불합격")
            except (ValueError, TypeError, KeyError, InvalidOperation, OverflowError) as exc:
                message = f"{kind}: {exc}"
            findings.append(Finding(key, rule.get("name", key), rule.get("severity", "ERROR"),
                rule.get("blocks_structure", True), layer, fid, field, message, geom, value, params))
    return findings


def blocked(findings):
    return any(f.severity == "ERROR" and f.blocks_structure and f.status == "OPEN" for f in findings)
