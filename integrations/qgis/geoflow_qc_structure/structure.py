"""Preview and output planning: no writes to input layers."""
from decimal import Decimal, ROUND_HALF_UP
from .catalog import validate_field
from .qc import run_qc, blocked


def operation(name, params, attrs, geom, spatial, target):
    if name == "KEEP":
        return attrs[params.get("source_field", target)]
    if name == "COPY":
        return attrs[params["source_field"]]
    if name == "CONSTANT":
        return params["value"]
    if name in {"LENGTH", "AREA", "ANGLE"}:
        return spatial.measure(geom, params, name)
    if name == "CODE_MAP":
        value = attrs[params["source_field"]]
        mapping = params["mapping"]
        if str(value) in mapping:
            return mapping[str(value)]
        if "fallback" in params:
            return params["fallback"]
        raise ValueError("코드 매핑 없음")
    if name == "CONDITION":
        return params["then"] if attrs[params["source_field"]] == params["equals"] else params["else"]
    if name in {"START_REFERENCE", "END_REFERENCE", "SPATIAL_LOOKUP"}:
        return spatial.lookup(geom, params, name)
    raise ValueError(f"Unknown operation: {name}")


def plan(profile, catalog):
    out = []
    seen = set()
    for key, rule in profile.get("field_rules", {}).items():
        field = validate_field(rule.get("field") or catalog[key])
        if not field.get("active", True):
            continue
        target = rule.get("target", field["physical_name"])
        field = validate_field(dict(field, physical_name=target))
        if target.casefold() in seen:
            raise ValueError(f"Duplicate output field: {target}")
        seen.add(target.casefold())
        out.append((key, rule, field))
    if not out:
        raise ValueError("No active output fields")
    return out


def preview(layer, rows, profile, fields, spatial):
    findings = run_qc(layer, rows, profile.get("qc_rules", {}), spatial, "PRE")
    if blocked(findings):
        return findings, [], [], []
    fields = plan(profile, fields)
    output, changes = [], []
    for fid, attrs, geom in rows:
        values = {}
        for key, rule, field in fields:
            target = field["physical_name"]
            old = attrs.get(target)
            name = rule["operation"]
            try:
                new = operation(name, rule.get("params", {}), attrs, geom, spatial, target)
                if new is None and "default_value" in field:
                    new = field["default_value"]
                if new is not None and field["data_type"] in {"NUMERIC", "DECIMAL"}:
                    new = Decimal(str(new)).quantize(Decimal(1).scaleb(-field["scale"]), rounding=ROUND_HALF_UP)
                status = "UNCHANGED" if old == new else "READY"
                values[target] = new
            except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                new, status = None, f"ERROR: {exc}"
            changes.append((fid, target, old, new, name, key, status))
        output.append((fid, values, geom))
    return findings, changes, output, [f for _, _, f in fields]


def post_qc(layer, rows, profile, fields, spatial):
    rules = dict(profile.get("qc_rules", {}))
    for field in fields:
        target = field["physical_name"]
        kind = field["data_type"]
        if kind == "GEOMETRY":
            continue
        checks = [("TYPE_CHECK", {"data_type": kind})]
        if field.get("required"):
            checks.append(("REQUIRED", {}))
        if not field.get("nullable", True):
            checks.append(("NULL_CHECK", {}))
        if kind in {"CHAR", "VARCHAR"}:
            checks.append(("LENGTH_CHECK", {"length": field["length"]}))
        if kind in {"NUMERIC", "DECIMAL"}:
            checks.extend([("PRECISION_CHECK", field), ("SCALE_CHECK", field)])
        if field.get("reference_codes"):
            checks.append(("REFERENCE_CODE_VALID", {"codes": field["reference_codes"]}))
        for check, params in checks:
            rules[f"output:{target}:{check}"] = dict(type=check, field=target, params=params, phase="POST")
    return run_qc(layer, rows, rules, spatial, "POST")
