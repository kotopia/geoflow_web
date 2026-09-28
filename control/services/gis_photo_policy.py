"""Central GIS photo catalogue: policy -> templates -> variants -> slots."""
from __future__ import annotations

import hashlib
import json
import re
from uuid import UUID, uuid4

from psycopg2.extras import Json

from control.services.gis_catalog_navigation import category_tree


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
    cur.execute("""SELECT to_regclass('gis.photo_policy') IS NOT NULL
        AND to_regclass('gis.photo_template') IS NOT NULL
        AND to_regclass('gis.photo_variant') IS NOT NULL
        AND to_regclass('gis.photo_slot') IS NOT NULL
        AND to_regclass('gis.photo_policy_template') IS NOT NULL""")
    return bool(cur.fetchone()[0])


def _dicts(cur):
    names = [column[0] for column in cur.description]
    return [dict(zip(names, row)) for row in cur.fetchall()]


def _json_object(value, label):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError as exc:
            raise PhotoPolicyError(f"{label} JSON이 올바르지 않습니다.") from exc
    if not isinstance(value, dict):
        raise PhotoPolicyError(f"{label} JSON이 객체가 아닙니다.")
    return value


def snapshot(cur):
    if not ready(cur):
        raise PhotoPolicyError("중앙 사진 정책 스키마가 준비되지 않았습니다.")
    cur.execute("""SELECT id::text,code,name,description,active,sort_order
        FROM gis.photo_template ORDER BY sort_order,code,id""")
    templates = _dicts(cur)
    cur.execute("""SELECT id::text,template_id::text,code,name,description,active,sort_order
        FROM gis.photo_variant ORDER BY template_id,sort_order,code,id""")
    variants = _dicts(cur)
    cur.execute("""SELECT id::text,variant_id::text,code,name,description,
        min_count,max_count,sort_order,active,extra_schema
        FROM gis.photo_slot ORDER BY variant_id,sort_order,code,id""")
    slots = _dicts(cur)
    for slot in slots:
        slot["extra_schema"] = _json_object(slot["extra_schema"], "사진 항목 추가 입력")
    cur.execute("""SELECT id::text,lv2_id::text,lv3_id::text,layer_id::text,
        active,sort_order,description FROM gis.photo_policy ORDER BY sort_order,id""")
    policies = _dicts(cur)
    cur.execute("""SELECT id::text,policy_id::text,template_id::text,sort_order,active
        FROM gis.photo_policy_template ORDER BY policy_id,sort_order,id""")
    policy_templates = _dicts(cur)
    body = [templates, variants, slots, policies, policy_templates]
    revision = hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False,
        separators=(",", ":"), default=str).encode()).hexdigest()
    return {"templates": templates, "variants": variants, "slots": slots,
            "policies": policies, "policy_templates": policy_templates,
            "revision": revision}


def catalog_options(cur):
    navigation = category_tree(cur)
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
    return {**navigation, "lv3": lv3, "layers": _dicts(cur)}


def validate_extra_schema(value):
    if not isinstance(value, dict) or set(value) != {"fields"} or not isinstance(value["fields"], list):
        raise PhotoPolicyError("추가 입력 정의는 fields 목록이어야 합니다.")
    if len(value["fields"]) > 30:
        raise PhotoPolicyError("추가 입력은 최대 30개입니다.")
    keys = set()
    for field in value["fields"]:
        if not isinstance(field, dict) or not isinstance(field.get("key"), str) or not field["key"].isidentifier():
            raise PhotoPolicyError("추가 입력 키가 올바르지 않습니다.")
        if field["key"] in keys or field.get("kind") not in ("text", "integer", "decimal", "boolean", "date", "datetime"):
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


def _code(value, label):
    result = str(value or "").strip().upper()
    if not re.fullmatch(r"[A-Z][A-Z0-9_]*", result):
        raise PhotoPolicyError(f"{label} 코드를 확인하세요.")
    return result


def _order(value):
    try:
        return int(value or 0)
    except (TypeError, ValueError) as exc:
        raise PhotoPolicyError("순서가 올바르지 않습니다.") from exc


def mutate(cur, payload):
    kind, action = payload.get("kind"), payload.get("action")
    if kind not in ("template", "variant", "slot", "policy") or action not in ("save", "deactivate"):
        raise PhotoPolicyError("지원하지 않는 사진 정의 작업입니다.")
    table = {"template": "photo_template", "variant": "photo_variant",
             "slot": "photo_slot", "policy": "photo_policy"}[kind]
    item_id = uid(payload["id"], "정의 ID") if payload.get("id") else str(uuid4())
    if action == "deactivate":
        if kind == "template" and _exists(cur, """SELECT 1 FROM gis.photo_policy_template pt
                JOIN gis.photo_policy p ON p.id=pt.policy_id
                WHERE pt.template_id=%s AND pt.active AND p.active""", [item_id]):
            raise PhotoPolicyError("활성 사진 정책에서 사용하는 템플릿입니다. 먼저 정책 연결을 변경하세요.")
        cur.execute(f"UPDATE gis.{table} SET active=false,updated_at=now() WHERE id=%s", [item_id])
        if cur.rowcount != 1:
            raise PhotoPolicyError("사진 정의를 찾을 수 없습니다.")
        return item_id

    name = str(payload.get("name") or "").strip()
    description = str(payload.get("description") or "").strip()
    if kind in ("template", "variant", "slot") and not 1 <= len(name) <= 120:
        raise PhotoPolicyError("이름은 1~120자여야 합니다.")
    order = _order(payload.get("sort_order"))
    if kind == "template":
        cur.execute("""INSERT INTO gis.photo_template(id,code,name,description,sort_order)
          VALUES (%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET code=EXCLUDED.code,
          name=EXCLUDED.name,description=EXCLUDED.description,sort_order=EXCLUDED.sort_order,
          active=true,updated_at=now()""", [item_id,_code(payload.get("code"), "템플릿"),name,description,order])
    elif kind == "variant":
        template = uid(payload.get("template_id"), "템플릿")
        if not _exists(cur, "SELECT 1 FROM gis.photo_template WHERE id=%s AND active", [template]):
            raise PhotoPolicyError("활성 템플릿을 찾을 수 없습니다.")
        cur.execute("""INSERT INTO gis.photo_variant(id,template_id,code,name,description,sort_order)
          VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET
          template_id=EXCLUDED.template_id,code=EXCLUDED.code,name=EXCLUDED.name,
          description=EXCLUDED.description,sort_order=EXCLUDED.sort_order,active=true,updated_at=now()""",
          [item_id,template,_code(payload.get("code"), "Variant"),name,description,order])
    elif kind == "slot":
        variant = uid(payload.get("variant_id"), "Variant")
        try:
            minimum, maximum = int(payload.get("min_count", 1)), int(payload.get("max_count", 1))
        except (ValueError, TypeError) as exc:
            raise PhotoPolicyError("사진 수량이 올바르지 않습니다.") from exc
        if not 0 <= minimum <= maximum <= 100:
            raise PhotoPolicyError("사진 수량이 올바르지 않습니다.")
        extra = validate_extra_schema(payload.get("extra_schema", {"fields": []}))
        if not _exists(cur, "SELECT 1 FROM gis.photo_variant WHERE id=%s AND active", [variant]):
            raise PhotoPolicyError("활성 Variant를 찾을 수 없습니다.")
        cur.execute("""INSERT INTO gis.photo_slot(id,variant_id,code,name,description,
          min_count,max_count,sort_order,extra_schema) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)
          ON CONFLICT(id) DO UPDATE SET variant_id=EXCLUDED.variant_id,code=EXCLUDED.code,
          name=EXCLUDED.name,description=EXCLUDED.description,min_count=EXCLUDED.min_count,
          max_count=EXCLUDED.max_count,sort_order=EXCLUDED.sort_order,
          extra_schema=EXCLUDED.extra_schema,active=true,updated_at=now()""",
          [item_id,variant,_code(payload.get("code"), "사진 항목"),name,description,
           minimum,maximum,order,Json(extra)])
    else:
        lv2 = uid(payload.get("lv2_id"), "L2")
        lv3 = uid(payload["lv3_id"], "L3") if payload.get("lv3_id") else None
        layer = uid(payload.get("layer_id"), "레이어")
        raw_templates = payload.get("template_ids")
        if not isinstance(raw_templates, list) or not raw_templates:
            raise PhotoPolicyError("적용할 템플릿을 하나 이상 선택하세요.")
        template_ids = []
        for value in raw_templates:
            template_id = uid(value, "템플릿")
            if template_id not in template_ids:
                template_ids.append(template_id)
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
        for template_id in template_ids:
            if not _exists(cur, "SELECT 1 FROM gis.photo_template WHERE id=%s AND active", [template_id]):
                raise PhotoPolicyError("활성 템플릿을 찾을 수 없습니다.")
        cur.execute("""INSERT INTO gis.photo_policy(id,lv2_id,lv3_id,layer_id,sort_order,description)
          VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(id) DO UPDATE SET lv2_id=EXCLUDED.lv2_id,
          lv3_id=EXCLUDED.lv3_id,layer_id=EXCLUDED.layer_id,sort_order=EXCLUDED.sort_order,
          description=EXCLUDED.description,active=true,updated_at=now()""",
          [item_id,lv2,lv3,layer,order,description])
        cur.execute("UPDATE gis.photo_policy_template SET active=false,updated_at=now() WHERE policy_id=%s",
                    [item_id])
        for index, template_id in enumerate(template_ids):
            cur.execute("""INSERT INTO gis.photo_policy_template
              (id,policy_id,template_id,sort_order,active) VALUES (%s,%s,%s,%s,true)
              ON CONFLICT(policy_id,template_id) DO UPDATE SET sort_order=EXCLUDED.sort_order,
              active=true,updated_at=now()""", [str(uuid4()),item_id,template_id,index])
    return item_id


def resolve(data, scope_rows, layer_id):
    """Resolve one L3-specific/L2-default policy and return its ordered catalogue."""
    candidates = []
    for policy in data["policies"]:
        if not policy["active"] or policy["layer_id"] != str(layer_id):
            continue
        for lv2, lv3 in scope_rows:
            if policy["lv2_id"] == str(lv2) and (policy["lv3_id"] is None or policy["lv3_id"] == str(lv3)):
                candidates.append((int(policy["lv3_id"] is not None), policy))
                break
    if not candidates:
        return None
    priority = max(rank for rank, _ in candidates)
    winners = {policy["id"]: policy for rank,policy in candidates if rank == priority}
    if len(winners) != 1:
        raise PhotoPolicyConflict("동일한 레이어에 같은 우선순위 사진 정책이 여러 개 적용됩니다.")
    policy = next(iter(winners.values()))
    templates_by_id = {row["id"]: row for row in data["templates"] if row["active"]}
    variants = [row for row in data["variants"] if row["active"]]
    slots = [row for row in data["slots"] if row["active"]]
    links = sorted((row for row in data["policy_templates"]
                    if row["active"] and row["policy_id"] == policy["id"]),
                   key=lambda row: (row["sort_order"], row["id"]))
    expanded = []
    for link in links:
        template = templates_by_id.get(link["template_id"])
        if not template:
            continue
        template_variants = []
        for variant in sorted((row for row in variants if row["template_id"] == template["id"]),
                              key=lambda row: (row["sort_order"], row["code"], row["id"])):
            template_variants.append({**variant, "slots": sorted(
                (row for row in slots if row["variant_id"] == variant["id"]),
                key=lambda row: (row["sort_order"], row["code"], row["id"]))})
        if template_variants:
            expanded.append({**template, "sort_order": link["sort_order"],
                             "variants": template_variants})
    if not expanded:
        raise PhotoPolicyError("정책에 활성 사진 Template/Variant가 없습니다.")
    return {"policy_id": policy["id"], "layer_id": str(layer_id), "templates": expanded}
