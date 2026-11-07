"""Preview and output planning: no writes to input layers."""
from decimal import Decimal, ROUND_HALF_UP, localcontext
from datetime import date, datetime
from .catalog import validate_field
from .qc import run_qc, blocked, Finding


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
        from .references import convert
        return convert(attrs[params["source_field"]], params)
    if name == "AGGREGATE":
        return spatial.aggregate(geom, params)[params["statistic"]]
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


def effective_rules(profile, fields):
    generated = {field['physical_name'] for _, rule, field in fields if rule['operation'] not in {'COPY', 'KEEP'}}
    rules = {}
    for key, rule in profile.get('qc_rules', {}).items():
        rule = dict(rule)
        if rule.get('field') in generated and rule['type'] not in {'GEOMETRY_EXISTS', 'GEOMETRY_VALID', 'GEOMETRY_TYPE'}:
            rule['phase'] = 'POST'
        rules[key] = rule
    return rules


def pre_qc(layer, rows, profile, fields, spatial):
    findings = run_qc(layer, rows, effective_rules(profile, fields), spatial, 'PRE')
    for _, rule, field in fields:
        params = rule.get("params", {})
        source = params.get("source_field", field["physical_name"])
        try:
            if rule["operation"] in {"COPY", "KEEP", "CODE_MAP", "CONDITION"} and any(source not in attrs for _, attrs, _ in rows):
                raise ValueError(f"Missing input field: {source}")
            if rule["operation"] == "AGGREGATE":
                spatial.validate_aggregate(params)
        except (ValueError, KeyError, TypeError) as exc:
            for fid, _, geom in rows:
                findings.append(Finding("input", "Operation input", "ERROR", True, layer, fid,
                                        field["physical_name"], str(exc), geom, None, params))
    return findings


def preview(layer, rows, profile, fields, spatial):
    fields = plan(profile, fields)
    findings = pre_qc(layer, rows, profile, fields, spatial)
    if blocked(findings):
        # Keep field-level error results available for inspection.
        return findings, [(fid, f["physical_name"], attrs.get(f["physical_name"]), None, r["operation"], k,
                           "ERROR: Pre-QC") for fid, attrs, _ in rows for k, r, f in fields], [], [f for _, _, f in fields]
    output, changes = [], []
    for fid, attrs, geom in rows:
        spatial.current_feature_id = fid
        values = {}
        for key, rule, field in fields:
            target = field["physical_name"]
            old = attrs.get(target)
            name = rule["operation"]
            try:
                new = operation(name, rule.get("params", {}), attrs, geom, spatial, target)
                if name == "CONSTANT" and isinstance(new, str):
                    if field["data_type"] == "DATE":
                        new = date.fromisoformat(new)
                    if field["data_type"] in {"DATETIME", "TIMESTAMP"}:
                        new = datetime.fromisoformat(new)
                if new is not None and field["data_type"] in {"NUMERIC", "DECIMAL"}:
                    with localcontext() as ctx:
                        ctx.prec = max(50, field["precision"] + field["scale"] + 10)
                        new = Decimal(str(new)).quantize(Decimal(1).scaleb(-field["scale"]), rounding=ROUND_HALF_UP)
                status = "UNCHANGED" if target in attrs and old == new else "READY"
                values[target] = new
            except (ValueError, KeyError, TypeError, ArithmeticError) as exc:
                new, status = None, f"ERROR: {exc}"
                values[target] = None
            changes.append((fid, target, old, new, name, key, status))
        output.append((fid, values, geom))
    findings.extend(post_qc(layer, output, profile, [f for _, _, f in fields], spatial))
    for fid, attrs, geom in output:
        for _, rule, field in fields:
            if rule["operation"] == "AGGREGATE" and attrs.get(field["physical_name"]) is None:
                findings.append(Finding("aggregate_empty", "유효 심도 없음", "WARNING", False, layer,
                    fid, field["physical_name"], "유효값 없음: NULL 반환", geom, None, None))
    return findings, changes, output, [f for _, _, f in fields]


def post_qc(layer, rows, profile, fields, spatial):
    active = {f['semantic_key']: f for f in fields}
    rules = effective_rules(profile, [(key, rule, active[key]) for key, rule in profile.get('field_rules', {}).items() if key in active])
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

