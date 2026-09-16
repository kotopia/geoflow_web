import logging
from uuid import uuid4

from django.contrib import messages
from django.http import Http404
from django.shortcuts import redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods

from control.decorators import require_central_admin
from control.models import GroupDBConfig
from control.services.gis_admin import tenant_cursor
from geoflow_ops.gis import form_definitions as definitions

logger = logging.getLogger(__name__)


def _mutate(cur, data):
    action = data.get("action")
    if action == "code_group":
        cur.execute("""INSERT INTO gis.ref_code_group(id,group_key,name,active)
            VALUES (%s,%s,%s,%s) ON CONFLICT(group_key)
            DO UPDATE SET name=EXCLUDED.name,active=EXCLUDED.active""",
            [str(uuid4()),definitions.text(data.get("key")),definitions.text(data.get("label")),data.get("active")=="true"])
    elif action == "code_value":
        group = definitions.identifier(data.get("code_group"))
        cur.execute("SELECT 1 FROM gis.ref_code_group WHERE id=%s AND active FOR UPDATE", [group])
        if not cur.fetchone():
            raise definitions.DefinitionError("활성 코드 그룹을 선택하세요.")
        cur.execute("""INSERT INTO gis.ref_code_value(id,group_id,code,label,sort_order,active)
            VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT(group_id,code)
            DO UPDATE SET label=EXCLUDED.label,sort_order=EXCLUDED.sort_order,active=EXCLUDED.active""",
            [str(uuid4()),group,definitions.text(data.get("code")),definitions.text(data.get("label")),
             int(data.get("sort_order",0)),data.get("active")=="true"])
    elif action == "profile":
        base = definitions.identifier(data.get("base_profile"))
        cur.execute("SELECT 1 FROM gis.profile WHERE id=%s AND active FOR SHARE",[base])
        if not cur.fetchone():
            raise definitions.DefinitionError("기준 프로필을 선택하세요.")
        new_id = str(uuid4())
        cur.execute("""INSERT INTO gis.profile(id,code,name,municipality,version,description)
            VALUES (%s,%s,%s,%s,'1',%s)""", [new_id,definitions.text(data.get("key")),
            definitions.text(data.get("label")),str(data.get("municipality", ""))[:120],
            "기존 시설물·기본 필드 구성을 복사하여 생성한 업무 그룹"])
        for table, target, columns in [
            ("profile_feature","feature_type_id","enabled,required,sort_order"),
            ("profile_field","field_def_id","enabled,required,editable,visible,sort_order")]:
            # Table and column names are fixed in source, never request input.
            cur.execute(f"""INSERT INTO gis.{table}(id,profile_id,{target},{columns})
                SELECT gen_random_uuid(),%s,{target},{columns} FROM gis.{table} WHERE profile_id=%s""",[new_id,base])
    else:
        if not definitions.ready(cur):
            raise definitions.DefinitionError("추가 항목 메타데이터 구조가 아직 적용되지 않았습니다.")
        if action == "item":
            kind = data.get("kind")
            config = ({"data_type":data.get("data_type")} if kind=="scalar" else
                      {"min_count":int(data.get("min_count",0)),"max_count":int(data.get("max_count",20))}
                      if kind=="photo" else {})
            definitions.add_item(cur,feature_id=data.get("feature"),label=data.get("label"),
                                 kind=kind,config=config,code_group_key=data.get("reference") or None)
        elif action in ("attach_profile","promote"):
            definitions.attach_profile(cur,item_id=data.get("item"),profile_id=data.get("profile"),
                                       required=data.get("required")=="true",promote=action=="promote")
        else:
            raise definitions.DefinitionError("지원하지 않는 요청입니다.")


@require_central_admin
@require_http_methods(["GET","POST"])
def dashboard(request):
    groups = list(GroupDBConfig.objects.using("default").filter(group__status="active")
                  .values("group_id","group__name").order_by("group__name"))
    raw_group = request.POST.get("tenant") if request.method=="POST" else request.GET.get("tenant")
    context = {"groups":groups,"selected_tenant":raw_group,"extension_ready":False}
    if not raw_group:
        return render(request,"control/gis/definitions.html",context)
    try:
        group_id = definitions.identifier(raw_group)
        with tenant_cursor(group_id,write=request.method=="POST") as cur:
            if request.method=="POST":
                _mutate(cur,request.POST)
            else:
                context["profiles"] = definitions.rows(cur,"""SELECT p.id::text,p.name,p.code,p.municipality,
                    (SELECT count(*) FROM gis.project_profile j WHERE j.profile_id=p.id) AS explicit_projects
                    FROM gis.profile p WHERE p.active ORDER BY p.name""")
                context["features"] = definitions.rows(cur,"SELECT id::text,label FROM gis.meta_feature_type WHERE active ORDER BY sort_order,label")
                context["code_groups"] = definitions.rows(cur,"SELECT id::text,group_key,name,active FROM gis.ref_code_group ORDER BY group_key")
                context["code_values"] = definitions.rows(cur,"""SELECT g.name AS group_name,v.code,v.label,v.active,v.sort_order
                    FROM gis.ref_code_value v JOIN gis.ref_code_group g ON g.id=v.group_id ORDER BY g.group_key,v.sort_order,v.code""")
                context["extension_ready"] = definitions.ready(cur)
                if context["extension_ready"]:
                    context["items"] = definitions.catalog(cur)
                    context["links"] = definitions.rows(cur,"""SELECT p.name AS profile_name,i.label,
                        l.required_on_complete,l.enabled FROM gis.profile_form_item l
                        JOIN gis.profile p ON p.id=l.profile_id JOIN gis.form_item i ON i.id=l.item_id
                        ORDER BY p.name,i.label""")
        if request.method=="POST":
            messages.success(request,"정의를 저장했습니다.")
            return redirect(reverse("control:gis_definitions")+"?tenant="+group_id)
    except Http404:
        raise
    except (definitions.DefinitionError,ValueError) as exc:
        context["error"] = str(exc) if isinstance(exc,definitions.DefinitionError) else "숫자 입력을 확인하세요."
    except Exception:
        logger.warning("GIS definition administration failed")
        context["error"] = "정의를 읽거나 저장하지 못했습니다. 연결 상태와 메타데이터 적용 상태를 확인하세요."
    return render(request,"control/gis/definitions.html",context,status=400 if context.get("error") else 200)
