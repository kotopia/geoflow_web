"""Central GIS-only photo catalogue and deterministic project policy resolver."""
from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID, uuid4

from psycopg2.extras import Json


class PhotoPolicyError(ValueError):
    pass


class PhotoPolicyConflict(PhotoPolicyError):
    code = "PHOTO_POLICY_CONFLICT"


def uid(value, label="ID"):
    try:
        return str(UUID(str(value)))
    except (TypeError, ValueError, AttributeError) as exc:
        raise PhotoPolicyError(f"{label}가 올바르지 않습니다.") from exc


def ready(cur):
    cur.execute("SELECT to_regclass('gis.photo_policy') IS NOT NULL AND "
                "to_regclass('gis.photo_template') IS NOT NULL AND "
                "to_regclass('gis.photo_slot') IS NOT NULL")
    return bool(cur.fetchone()[0])


def _dicts(cur):
    names = [c[0] for c in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def snapshot(cur):
    if not ready(cur):
        raise PhotoPolicyError("중앙 사진 정책 스키마가 준비되지 않았습니다.")
    cur.execute("""SELECT id::text,code,name,description,capture_mode,active,sort_order
        FROM gis.photo_template ORDER BY sort_order,code""")
    templates = _dicts(cur)
    cur.execute("""SELECT id::text,template_id::text,code,name,description,
        min_count,max_count,sort_order,active,extra_schema
        FROM gis.photo_slot ORDER BY template_id,sort_order,code""")
    slots = _dicts(cur)
    cur.execute("""SELECT p.id::text,p.lv2_id::text,p.lv3_id::text,p.layer_id::text,
        p.default_capture_mode,p.direct_template_id::text,p.indirect_template_id::text,
        p.allow_extra_photo,p.active,p.sort_order,p.description
        FROM gis.photo_policy p ORDER BY p.sort_order,p.id""")
    policies = _dicts(cur)
    revision = hashlib.sha256(json.dumps([templates, slots, policies], sort_keys=True,
        ensure_ascii=False, separators=(",", ":"), default=str).encode()).hexdigest()
    return {"templates": templates, "slots": slots, "policies": policies, "revision": revision}


def catalog_options(cur):
    cur.execute("""SELECT id::text,code,name,level FROM catalog.category_node
        WHERE level IN (1,2) AND active ORDER BY level,ord,code""")
    nodes = _dicts(cur)
    cur.execute("""SELECT parent_id::text,child_id::text FROM catalog.category_parent""")
    parents = _dicts(cur)
    cur.execute("""SELECT s.l2_id::text AS lv2_id,o.id::text,o.code,o.name
        FROM catalog.category_option_set s
        JOIN catalog.category_facet_option o ON o.facet_id=s.facet_id AND o.active
        JOIN catalog.category_facet f ON f.id=s.facet_id AND f.active
        WHERE s.level_no=3 AND
          (NOT EXISTS (SELECT 1 FROM catalog.category_option_pick pick
                       WHERE pick.l2_id=s.l2_id AND pick.level_no=3)
           OR EXISTS (SELECT 1 FROM catalog.category_option_pick pick
                      WHERE pick.l2_id=s.l2_id AND pick.level_no=3 AND pick.option_id=o.id))
        ORDER BY s.l2_id,s.ord,o.ord,o.name""")
    lv3 = _dicts(cur)
    cur.execute("""SELECT lc.catalog_item_id::text AS lv2_id,
        l.id::text,l.standard_name,l.label,l.physical_name
        FROM gis.definition_layer_catalog lc JOIN gis.definition_layer l ON l.id=lc.layer_id
        WHERE lc.catalog_level=2 AND l.active ORDER BY l.sort_order,l.standard_name""")
    return {"nodes": nodes, "parents": parents, "lv3": lv3, "layers": _dicts(cur)}


def validate_extra_schema(value):
    if not isinstance(value, dict) or set(value) != {"fields"} or not isinstance(value["fields"], list):
        raise PhotoPolicyError("추가 입력 정의는 fields 목록이어야 합니다.")
    if len(value["fields"]) > 30:
        raise PhotoPolicyError("추가 입력은 최대 30개입니다.")
    keys = set()
    for field in value["fields"]:
        if not isinstance(field, dict) or not isinstance(field.get("key"), str) or not field["key"].isidentifier():
            raise PhotoPolicyError("추가 입력 키가 올바르지 않습니다.")
        if field["key"] in keys or field.get("kind") not in ("text","integer","decimal","boolean","date","datetime"):
            raise PhotoPolicyError("추가 입력 키 또는 유형이 중복되거나 올바르지 않습니다.")
        if not isinstance(field.get("label"), str) or not field["label"].strip():
            raise PhotoPolicyError("추가 입력 표시명을 입력하세요.")
        if not isinstance(field.get("required", False), bool):
            raise PhotoPolicyError("추가 입력 필수 여부가 올바르지 않습니다.")
        keys.add(field["key"])
    return value


def _exists(cur, sql, params):
    cur.execute(sql, params)
    return bool(cur.fetchone())


def mutate(cur, payload):
    kind = payload.get("kind")
    action = payload.get("action")
    if kind not in ("template", "slot", "policy") or action not in ("save", "deactivate"):
        raise PhotoPolicyError("지원하지 않는 사진 정의 작업입니다.")
    table = {"template":"photo_template", "slot":"photo_slot", "policy":"photo_policy"}[kind]
    item_id = uid(payload["id"], "정의 ID") if payload.get("id") else str(uuid4())
    if action == "deactivate":
        if kind == "template" and _exists(cur,"""SELECT 1 FROM gis.photo_policy WHERE active AND
            (direct_template_id=%s OR indirect_template_id=%s)""",[item_id,item_id]):
            raise PhotoPolicyError("활성 사진 정책에서 사용하는 템플릿입니다. 먼저 정책을 변경하세요.")
        cur.execute(f"UPDATE gis.{table} SET active=false,updated_at=now() WHERE id=%s", [item_id])
        if cur.rowcount != 1:
            raise PhotoPolicyError("사진 정의를 찾을 수 없습니다.")
        return item_id

    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    if kind in ("template", "slot") and not 1 <= len(name) <= 120:
        raise PhotoPolicyError("이름은 1~120자여야 합니다.")
    try:
        order = int(payload.get("sort_order") or 0)
    except (TypeError, ValueError) as exc:
        raise PhotoPolicyError("순서가 올바르지 않습니다.") from exc
    if kind == "template":
        code = str(payload.get("code") or "").strip().upper()
        mode = payload.get("capture_mode")
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*",code) or mode not in ("DIRECT","INDIRECT","GENERAL"):
            raise PhotoPolicyError("템플릿 코드 또는 촬영방식을 확인하세요.")
        if _exists(cur,"""SELECT 1 FROM gis.photo_policy WHERE active AND
          ((direct_template_id=%s AND %s <> 'DIRECT') OR
           (indirect_template_id=%s AND %s <> 'INDIRECT'))""",[item_id,mode,item_id,mode]):
            raise PhotoPolicyError("정책에서 사용하는 템플릿의 촬영방식은 변경할 수 없습니다.")
        cur.execute("""INSERT INTO gis.photo_template(id,code,name,description,capture_mode,sort_order)
          VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET
          code=EXCLUDED.code,name=EXCLUDED.name,description=EXCLUDED.description,
          capture_mode=EXCLUDED.capture_mode,sort_order=EXCLUDED.sort_order,
          updated_at=now()""", [item_id,code,name,description,mode,order])
    elif kind == "slot":
        template = uid(payload.get("template_id"), "템플릿")
        code = str(payload.get("code") or "").strip().upper()
        try:
            minimum = int(payload.get("min_count", 1))
            maximum = int(payload.get("max_count", 1))
        except (ValueError, TypeError) as exc:
            raise PhotoPolicyError("사진 수량이 올바르지 않습니다.") from exc
        if not re.fullmatch(r"[A-Z][A-Z0-9_]*",code) or not 0 <= minimum <= maximum <= 100:
            raise PhotoPolicyError("사진 코드 또는 수량이 올바르지 않습니다.")
        extra = validate_extra_schema(payload.get("extra_schema", {"fields": []}))
        if not _exists(cur,"SELECT 1 FROM gis.photo_template WHERE id=%s AND active",[template]):
            raise PhotoPolicyError("활성 템플릿을 찾을 수 없습니다.")
        cur.execute("""INSERT INTO gis.photo_slot(id,template_id,code,name,description,
          min_count,max_count,sort_order,extra_schema) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
          ON CONFLICT(id) DO UPDATE SET code=EXCLUDED.code,name=EXCLUDED.name,
          description=EXCLUDED.description,min_count=EXCLUDED.min_count,
          max_count=EXCLUDED.max_count,sort_order=EXCLUDED.sort_order,
          extra_schema=EXCLUDED.extra_schema,updated_at=now()""",
          [item_id,template,code,name,description,minimum,maximum,order,Json(extra)])
    else:
        lv2 = uid(payload.get("lv2_id"), "L2")
        lv3 = uid(payload["lv3_id"], "L3") if payload.get("lv3_id") else None
        layer = uid(payload.get("layer_id"), "레이어")
        direct = uid(payload["direct_template_id"]) if payload.get("direct_template_id") else None
        indirect = uid(payload["indirect_template_id"]) if payload.get("indirect_template_id") else None
        mode = payload.get("default_capture_mode", "DIRECT")
        if mode not in ("DIRECT", "INDIRECT") or not (direct or indirect):
            raise PhotoPolicyError("기본 방식과 템플릿을 확인하세요.")
        if not _exists(cur,"SELECT 1 FROM catalog.category_node WHERE id=%s AND level=2 AND active",[lv2]):
            raise PhotoPolicyError("활성 L2 업무범위를 찾을 수 없습니다.")
        if lv3 and not _exists(cur,"""SELECT 1 FROM catalog.category_option_set s
            JOIN catalog.category_facet_option o ON o.facet_id=s.facet_id
            JOIN catalog.category_facet f ON f.id=s.facet_id
            WHERE s.l2_id=%s AND s.level_no=3 AND o.id=%s AND o.active AND f.active
              AND (NOT EXISTS(SELECT 1 FROM catalog.category_option_pick p WHERE p.l2_id=s.l2_id AND p.level_no=3)
                OR EXISTS(SELECT 1 FROM catalog.category_option_pick p WHERE p.l2_id=s.l2_id AND p.level_no=3 AND p.option_id=o.id))""",[lv2,lv3]):
            raise PhotoPolicyError("L3가 선택한 L2에 속하지 않습니다.")
        if not _exists(cur,"""SELECT 1 FROM gis.definition_layer_catalog lc
            JOIN gis.definition_layer l ON l.id=lc.layer_id AND l.active
            WHERE lc.catalog_level=2 AND lc.catalog_item_id=%s AND lc.layer_id=%s""",[lv2,layer]):
            raise PhotoPolicyError("L2에 연결된 활성 레이어만 선택할 수 있습니다.")
        for template_id, expected in ((direct,"DIRECT"),(indirect,"INDIRECT")):
            if template_id and not _exists(cur,
                "SELECT 1 FROM gis.photo_template WHERE id=%s AND active AND capture_mode=%s",[template_id,expected]):
                raise PhotoPolicyError("방식에 맞는 활성 템플릿이 아닙니다.")
        if not (direct if mode == "DIRECT" else indirect):
            raise PhotoPolicyError("기본 방식에 적용할 템플릿이 없습니다.")
        cur.execute("""INSERT INTO gis.photo_policy(id,lv2_id,lv3_id,layer_id,
          default_capture_mode,direct_template_id,indirect_template_id,
          allow_extra_photo,sort_order,description)
          VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET
          lv2_id=EXCLUDED.lv2_id,lv3_id=EXCLUDED.lv3_id,layer_id=EXCLUDED.layer_id,
          default_capture_mode=EXCLUDED.default_capture_mode,
          direct_template_id=EXCLUDED.direct_template_id,
          indirect_template_id=EXCLUDED.indirect_template_id,
          allow_extra_photo=EXCLUDED.allow_extra_photo,sort_order=EXCLUDED.sort_order,
          description=EXCLUDED.description,updated_at=now()""",
          [item_id,lv2,lv3,layer,mode,direct,indirect,
           payload.get("allow_extra_photo",True) is True,order,description])
    return item_id


def capture_mode(ext_data, default="DIRECT"):
    if isinstance(ext_data, str):
        try:
            ext_data = json.loads(ext_data)
        except ValueError as exc:
            raise PhotoPolicyError("객체 확장 데이터가 올바르지 않습니다.") from exc
    if not isinstance(ext_data, dict):
        raise PhotoPolicyError("객체 확장 데이터가 올바르지 않습니다.")
    photo = ext_data.get("photo", {})
    if not isinstance(photo, dict):
        raise PhotoPolicyError("사진 촬영방식이 올바르지 않습니다.")
    mode = photo.get("capture_mode", default)
    if mode not in ("DIRECT","INDIRECT"):
        raise PhotoPolicyError("사진 촬영방식은 DIRECT 또는 INDIRECT여야 합니다.")
    return mode


def resolve(data, scope_rows, layer_id, ext_data=None):
    """Use paired scope rows, not the flattened manifest capability list."""
    candidates = []
    for p in data["policies"]:
        if not p["active"] or p["layer_id"] != str(layer_id):
            continue
        for lv2, lv3 in scope_rows:
            if p["lv2_id"] == str(lv2) and (p["lv3_id"] is None or p["lv3_id"] == str(lv3)):
                candidates.append((int(p["lv3_id"] is not None), p))
                break
    if not candidates:
        return None
    priority = max(rank for rank, _ in candidates)
    winners = {p["id"]:p for rank,p in candidates if rank == priority}
    if len(winners) != 1:
        raise PhotoPolicyConflict("동일한 레이어에 같은 우선순위 사진 정책이 여러 개 적용됩니다.")
    policy = next(iter(winners.values()))
    mode = capture_mode(ext_data or {}, policy["default_capture_mode"])
    selected = policy["direct_template_id"] if mode == "DIRECT" else policy["indirect_template_id"]
    templates = {t["id"]:t for t in data["templates"] if t["active"]}
    if selected is None or selected not in templates:
        raise PhotoPolicyError("선택한 방식의 활성 사진 템플릿이 없습니다.")
    if templates[selected]["capture_mode"] != mode:
        raise PhotoPolicyError("사진 템플릿의 촬영방식이 정책과 일치하지 않습니다.")
    slots = [s for s in data["slots"] if s["template_id"] == selected and s["active"]]
    return {"policy_id":policy["id"], "capture_mode":mode,
            "allow_extra_photo":policy["allow_extra_photo"],
            "template":{**templates[selected],"slots":slots}}
