"""Local versioned provider. No QGIS or network dependency."""
import json
import os
from math import isfinite
import re
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile

TYPES = frozenset("TEXT VARCHAR CHAR SMALLINT INTEGER BIGINT REAL DOUBLE NUMERIC DECIMAL BOOLEAN DATE DATETIME TIMESTAMP UUID GEOMETRY".split())
KINDS = frozenset("POINT LINESTRING POLYGON MULTIPOINT MULTILINESTRING MULTIPOLYGON".split())
QC_TYPES = tuple("REQUIRED NULL_CHECK TYPE_CHECK LENGTH_CHECK PRECISION_CHECK SCALE_CHECK RANGE_CHECK REFERENCE_CODE_VALID GEOMETRY_EXISTS GEOMETRY_VALID GEOMETRY_TYPE DUPLICATE REFERENCE_EXISTS START_REFERENCE END_REFERENCE".split())
OP_PARAMS = {
    "KEEP": (), "COPY": ("source_field",), "CONSTANT": ("value",),
    "LENGTH": ("crs", "unit"), "AREA": ("crs", "unit"),
    "CODE_MAP": ("source_field", "mapping"),
    "START_REFERENCE": ("reference_layer", "reference_field", "crs", "radius"),
    "END_REFERENCE": ("reference_layer", "reference_field", "crs", "radius"),
    "SPATIAL_LOOKUP": ("reference_layer", "reference_field", "crs", "predicate"),
    "ANGLE": ("crs",), "CONDITION": ("source_field", "equals", "then", "else"),
}
IDENT = re.compile(r"[A-Za-z_][A-Za-z_0-9]{0,62}\Z")


def validate_field(field):
    kind = field["data_type"]
    if kind not in TYPES or not IDENT.fullmatch(field["physical_name"]) or not field["semantic_key"]:
        raise ValueError("Invalid field definition")
    if kind in {"CHAR", "VARCHAR"} and (type(field.get("length")) is not int or field["length"] < 1):
        raise ValueError("CHAR/VARCHAR requires a positive length")
    if kind in {"NUMERIC", "DECIMAL"}:
        p, s = field.get("precision"), field.get("scale")
        if type(p) is not int or type(s) is not int or not 0 <= s <= p <= 1000 or p == 0:
            raise ValueError("Invalid precision/scale")
    if kind == "GEOMETRY" and (field.get("geometry_type") not in KINDS or type(field.get("srid")) is not int or field["srid"] <= 0):
        raise ValueError("Geometry type and positive SRID required")
    for flag in ("nullable", "required", "active"):
        if flag in field and type(field[flag]) is not bool:
            raise ValueError(f"Invalid field flag: {flag}")
    return field


def validate_operation(name, params):
    if name not in OP_PARAMS or not isinstance(params, dict) or not set(OP_PARAMS[name]) <= params.keys():
        raise ValueError(f"Invalid parameters for {name}")
    optional = {
        "KEEP": {"source_field"}, "LENGTH": {"precision"}, "AREA": {"precision"},
        "CODE_MAP": {"fallback"}, "ANGLE": {"position"},
        "SPATIAL_LOOKUP": {"radius", "candidate_filter", "selection_policy"},
        "START_REFERENCE": {"candidate_filter", "selection_policy"},
        "END_REFERENCE": {"candidate_filter", "selection_policy"},
    }
    if params.keys() - set(OP_PARAMS[name]) - optional.get(name, set()):
        raise ValueError(f"Unknown parameters for {name}")
    for key in ("source_field", "reference_field", "reference_layer", "crs"):
        if key in params and (not isinstance(params[key], str) or not params[key].strip()):
            raise ValueError(f"Invalid parameter: {key}")
    if "radius" in params and (type(params["radius"]) not in {int, float} or not isfinite(params["radius"]) or params["radius"] < 0):
        raise ValueError("Invalid search radius")
    if "precision" in params and (type(params["precision"]) is not int or not 0 <= params["precision"] <= 15):
        raise ValueError("Invalid measurement precision")
    for key in ("mapping", "candidate_filter"):
        if key in params and not isinstance(params[key], dict):
            raise ValueError(f"Invalid parameter: {key}")
    for key, values in {"predicate": {"intersects","within","within_radius"}, "position": {"start","end"},
                        "selection_policy": {"unique","nearest"}}.items():
        if key in params and params[key] not in values:
            raise ValueError(f"Invalid parameter: {key}")
    if name in {"LENGTH","AREA"} and params["unit"] not in ({"m","km"} if name == "LENGTH" else {"m2","ha"}):
        raise ValueError("Invalid measurement unit")


def validate_profile(profile):
    for key in ("id", "name", "agency", "business_type", "layer_id", "description"):
        if not isinstance(profile[key], str) or (key in {"id", "name", "layer_id"} and not profile[key]):
            raise ValueError(f"Invalid profile {key}")
    if not IDENT.fullmatch(profile["id"]):
        raise ValueError("Invalid profile identifier")
    for rule in profile.get("field_rules", {}).values():
        if "field" in rule:
            validate_field(rule["field"])
        if "operation" in rule:
            op, params = rule["operation"], rule.get("params", {})
            validate_operation(op, params)
    for key, rule in profile.get("qc_rules", {}).items():
        if (not key or rule["type"] not in QC_TYPES or rule.get("severity", "ERROR") not in {"ERROR", "WARNING", "INFO"}
                or type(rule.get("blocks_structure", True)) is not bool
                or rule.get("phase", "PRE") not in {"PRE", "POST", "BOTH"}):
            raise ValueError(f"Invalid QC rule: {key}")
    return profile


class LocalCatalogProvider:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.bundled = json.loads((Path(__file__).parent / "resources/catalog.json").read_text(encoding="utf-8"))

    def get_layers(self):
        return deepcopy(self.bundled["layers"])

    def get_fields(self):
        fields = deepcopy(self.bundled["fields"])
        path = self.directory / "fields.json"
        if path.exists():
            for key, field in json.loads(path.read_text(encoding="utf-8")).items():
                if validate_field(field)["semantic_key"] != key:
                    raise ValueError("Field semantic key mismatch")
                fields[key] = field
        return fields

    def get_operations(self):
        return dict(OP_PARAMS)

    def get_qc_rule_types(self):
        return QC_TYPES

    def get_base_profiles(self):
        return deepcopy(self.bundled["profiles"])

    def profiles(self):
        profiles = self.get_base_profiles()
        for path in sorted((self.directory / "profiles").glob("*.json")):
            data = validate_profile(json.loads(path.read_text(encoding="utf-8")))
            if data["id"] in profiles and data["revision"] <= profiles[data["id"]]["revision"]:
                continue
            profiles[data["id"]] = data
        return profiles

    def resolve(self, profile_id, profiles=None, seen=()):
        profiles = self.profiles() if profiles is None else profiles
        if profile_id in seen:
            raise ValueError("Profile inheritance cycle")
        profile = deepcopy(validate_profile(profiles[profile_id]))
        base_id = profile.get("base_profile_id")
        if base_id:
            base = self.resolve(base_id, profiles, (*seen, profile_id))
            if base["layer_id"] != profile["layer_id"]:
                raise ValueError("Base profile layer mismatch")
            for key in ("field_rules", "qc_rules"):
                inherited = base.get(key, {})
                overrides = profile.get(key, {})
                profile[key] = inherited | {k: inherited.get(k, {}) | v for k, v in overrides.items()}
        for rule in profile.get("field_rules", {}).values():
            validate_operation(rule["operation"], rule.get("params", {}))
        return profile

    def save(self, profile):
        profile = deepcopy(validate_profile(profile))
        profiles = self.profiles()
        old = profiles.get(profile["id"], {})
        now = datetime.now(timezone.utc).isoformat()
        profile.update(revision=old.get("revision", 0)+1, created_at=old.get("created_at", now), updated_at=now)
        profiles[profile["id"]] = profile
        resolved = self.resolve(profile["id"], profiles)
        # Pin the resolved definition and field catalog for reproducibility.
        profile["snapshot"] = {"profile": {k:v for k,v in resolved.items() if k != "snapshot"}, "fields": self.get_fields()}
        path = self.directory / "profiles"
        path.mkdir(parents=True, exist_ok=True)
        dest = path / f'{profile["id"]}.{profile["revision"]:09}.json'
        if dest.exists():
            raise ValueError("Profile revision already exists")
        with NamedTemporaryFile("w", encoding="utf-8", dir=path, delete=False) as stream:
            json.dump(profile, stream, ensure_ascii=False, indent=2, allow_nan=False)
            temporary = Path(stream.name)
        try:
            # Exclusive atomic install: another editor cannot overwrite a revision.
            os.link(temporary, dest)
        finally:
            temporary.unlink()
        return profile
