"""Project additions and profile inheritance, without copying physical fields."""
from __future__ import annotations

import hashlib
import json
from uuid import UUID, uuid4


class DefinitionError(ValueError):
    pass


TABLES = ("gis.form_item", "gis.profile_form_item", "gis.project_form_item")


def rows(cur, sql, params=()):
    cur.execute(sql, params)
    keys = [c[0] for c in cur.description]
    return [dict(zip(keys, r)) for r in cur.fetchall()]


def ready(cur):
    cur.execute("SELECT to_regclass(%s),to_regclass(%s),to_regclass(%s)", TABLES)
    return all(cur.fetchone())


def identifier(value):
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        raise DefinitionError("식별자가 올바르지 않습니다.") from None


def text(value, maximum=120):
    value = str(value or "").strip()
    if not value or len(value) > maximum:
        raise DefinitionError("이름 또는 코드의 길이를 확인하세요.")
    return value


def validate_config(kind, config):
    if not isinstance(config, dict):
        raise DefinitionError("설정은 객체여야 합니다.")
    if kind == "scalar":
        if set(config) != {"data_type"} or config["data_type"] not in ("boolean", "text", "number", "date"):
            raise DefinitionError("속성 타입을 확인하세요.")
    elif kind == "photo":
        if set(config) != {"min_count", "max_count"}:
            raise DefinitionError("사진 최소·최대 수를 지정하세요.")
        lo, hi = config["min_count"], config["max_count"]
        if type(lo) is not int or type(hi) is not int or not 0 <= lo <= hi <= 100:
            raise DefinitionError("사진 수는 0~100 범위이며 최소는 최대 이하여야 합니다.")
    elif kind == "survey_relation":
        if config:
            raise DefinitionError("측량 관계는 기존 survey_link를 사용합니다.")
    else:
        raise DefinitionError("지원하지 않는 항목 종류입니다.")
    return dict(config)


def catalog(cur):
    return rows(cur, """SELECT i.id::text,i.feature_type_id::text,f.label AS feature_label,
        f.standard_name,i.label,i.kind,i.config,i.code_group_key,
        i.origin_project_id::text,i.active
        FROM gis.form_item i JOIN gis.meta_feature_type f ON f.id=i.feature_type_id
        ORDER BY f.sort_order,i.label,i.id""")


def add_item(cur, *, feature_id, label, kind, config, project_id=None, code_group_key=None):
    feature_id = identifier(feature_id)
    project_id = identifier(project_id) if project_id else None
    config = validate_config(kind, config)
    cur.execute("SELECT physical_name FROM gis.meta_feature_type WHERE id=%s AND active", [feature_id])
    feature = cur.fetchone()
    if not feature:
        raise DefinitionError("사용 가능한 시설물이 아닙니다.")
    if kind == "scalar":
        cur.execute("""SELECT 1 FROM information_schema.columns WHERE table_schema='gis'
                       AND table_name=%s AND column_name='ext_data' AND udt_name='jsonb'""", [feature[0]])
        if not cur.fetchone():
            raise DefinitionError("이 시설물에는 확장 속성 저장소가 없습니다.")
    if code_group_key:
        if kind != "scalar" or config["data_type"] != "text":
            raise DefinitionError("참조코드는 문자형 속성에서 사용합니다.")
        cur.execute("SELECT 1 FROM gis.ref_code_group WHERE group_key=%s AND active", [code_group_key])
        if not cur.fetchone():
            raise DefinitionError("활성 참조코드 그룹이 아닙니다.")
    item_id = str(uuid4())
    cur.execute("""INSERT INTO gis.form_item
        (id,feature_type_id,label,kind,config,origin_project_id,code_group_key)
        VALUES (%s,%s,%s,%s,%s::jsonb,%s,%s)""",
        [item_id, feature_id, text(label), kind, json.dumps(config), project_id, code_group_key or None])
    return item_id


def attach_profile(cur, *, item_id, profile_id, required=False, promote=False):
    item_id, profile_id = identifier(item_id), identifier(profile_id)
    cur.execute("SELECT origin_project_id FROM gis.form_item WHERE id=%s AND active FOR UPDATE", [item_id])
    item = cur.fetchone()
    if not item:
        raise DefinitionError("항목을 찾을 수 없습니다.")
    cur.execute("SELECT 1 FROM gis.profile WHERE id=%s AND active", [profile_id])
    if not cur.fetchone():
        raise DefinitionError("활성 그룹을 선택하세요.")
    if item[0] and not promote:
        raise DefinitionError("프로젝트 전용 항목은 공통 승격으로 등록하세요.")
    if item[0]:
        cur.execute("UPDATE gis.form_item SET origin_project_id=NULL,updated_at=now() WHERE id=%s", [item_id])
    cur.execute("""INSERT INTO gis.profile_form_item(profile_id,item_id,required_on_complete)
        VALUES (%s,%s,%s) ON CONFLICT (profile_id,item_id)
        DO UPDATE SET enabled=true,required_on_complete=EXCLUDED.required_on_complete""",
        [profile_id,item_id,bool(required)])


def attach_project(cur, *, item_id, project_id):
    item_id, project_id = identifier(item_id), identifier(project_id)
    cur.execute("""SELECT 1 FROM gis.form_item WHERE id=%s AND active
        AND (origin_project_id IS NULL OR origin_project_id=%s) FOR UPDATE""", [item_id,project_id])
    if not cur.fetchone():
        raise DefinitionError("이 프로젝트에서 사용할 수 없는 항목입니다.")
    cur.execute("""INSERT INTO gis.project_form_item(project_id,item_id) VALUES (%s,%s)
        ON CONFLICT(project_id,item_id) DO UPDATE SET enabled=true""", [project_id,item_id])


def resolve(cur, *, project_id, profile_id, feature_ids):
    project_id = identifier(project_id)
    profile_id = identifier(profile_id)
    feature_ids = [identifier(v) for v in feature_ids]
    if not feature_ids:
        return {"version": "gis-form-v1", "items": [], "groups": [], "revision": "empty", "client_integration_required": True}
    items = rows(cur, """SELECT i.id::text,i.feature_type_id::text,f.standard_name,i.label,i.kind,
        i.config,i.code_group_key,COALESCE(p.enabled,false) AS inherited,
        COALESCE(p.required_on_complete,false) AS required_on_complete
        FROM gis.form_item i JOIN gis.meta_feature_type f ON f.id=i.feature_type_id AND f.active
        LEFT JOIN gis.profile_form_item p ON p.item_id=i.id AND p.profile_id=%s AND p.enabled
        LEFT JOIN gis.project_form_item j ON j.item_id=i.id AND j.project_id=%s AND j.enabled
        WHERE i.active AND i.feature_type_id=ANY(%s::uuid[])
          AND (i.origin_project_id IS NULL OR i.origin_project_id=%s)
          AND (p.item_id IS NOT NULL OR j.item_id IS NOT NULL)
        ORDER BY f.sort_order,i.label,i.id""", [profile_id,project_id,feature_ids,project_id])
    for item in items:
        item["required_display"] = bool(item["inherited"])
        item["source"] = "profile" if item["inherited"] else "project"
        item["storage"] = ({"kind": "ext_data", "namespace": "gis_form", "key": item["id"]}
                           if item["kind"] == "scalar" else
                           {"kind": "ops.attachments", "purpose": "gis_form:" + item["id"]}
                           if item["kind"] == "photo" else {"kind": "gis.survey_link"})
    keys=sorted({i["code_group_key"] for i in items if i["code_group_key"]})
    groups={}
    if keys:
        values=rows(cur,"""SELECT g.group_key,g.name,v.code,v.label,v.sort_order
            FROM gis.ref_code_group g LEFT JOIN gis.ref_code_value v ON v.group_id=g.id
              AND v.active AND (v.valid_from IS NULL OR v.valid_from<=CURRENT_DATE)
              AND (v.valid_to IS NULL OR v.valid_to>=CURRENT_DATE)
            WHERE g.active AND g.group_key=ANY(%s)
            ORDER BY g.group_key,v.sort_order,v.code""",[keys])
        for value in values:
            group=groups.setdefault(value["group_key"],{"code_group_key":value["group_key"],"name":value["name"],"values":[]})
            if value["code"] is not None:
                group["values"].append({k:value[k] for k in ("code","label","sort_order")})
    canonical = json.dumps({"items":items,"groups":list(groups.values())},sort_keys=True,ensure_ascii=False,default=str).encode()
    return {"version": "gis-form-v1", "items": items,"groups":list(groups.values()),
            "revision": hashlib.sha256(canonical).hexdigest(),
            "client_integration_required": True}
