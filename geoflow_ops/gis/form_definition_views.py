import logging

from django.contrib.auth.decorators import login_required
from django.core.exceptions import PermissionDenied
from django.db import connections, transaction, DatabaseError
from django.http import JsonResponse
from django.shortcuts import render, redirect
from django.views.decorators.http import require_GET, require_http_methods

from . import form_definitions as definitions
from .views import _require_gis_view, _require_project_gis_access
from .qgis_views import _require_qgis_context, _require_project
from geoflow_ops.services.project_access import project_access_policy

logger = logging.getLogger(__name__)


@login_required
@require_GET
def definition_api(request, project_id):
    alias = _require_qgis_context(request)
    _project, _policy, plan = _require_project(request, alias, project_id)
    with connections[alias].cursor() as cur:
        if not definitions.ready(cur):
            return JsonResponse({"ok":False,"error":"form_definition_schema_pending"},status=503)
        payload = definitions.resolve(cur,project_id=project_id,profile_id=plan["profile"]["id"],
                                      feature_ids=[v["id"] for v in plan["layers"]])
    response = JsonResponse({"ok":True,**payload})
    response["Cache-Control"] = "private, no-store"
    return response


@login_required
@require_http_methods(["GET","POST"])
def project_configuration(request, project_id):
    alias = _require_gis_view(request)
    project, plan = _require_project_gis_access(request, alias, project_id)
    can_edit = project_access_policy(request,alias).can_edit_project(project.id)
    if request.method=="POST" and not can_edit:
        raise PermissionDenied("프로젝트 설정 권한이 없습니다.")
    feature_ids = [str(v["id"]) for v in plan["layers"]]
    context = {"project":project,"plan":plan,"can_edit":can_edit,"features":plan["layers"]}
    try:
        with transaction.atomic(using=alias):
            with connections[alias].cursor() as cur:
                context["ready"] = definitions.ready(cur)
                if not context["ready"] and request.method=="POST":
                    raise definitions.DefinitionError("추가 항목 메타데이터 구조가 아직 적용되지 않았습니다.")
                if context["ready"]:
                    available = [v for v in definitions.catalog(cur)
                                 if v["active"] and v["feature_type_id"] in feature_ids
                                 and v["origin_project_id"] in (None,str(project_id))]
                    context["profiles"] = definitions.rows(cur,"SELECT id::text,name FROM gis.profile WHERE active ORDER BY name")
                    if request.method=="POST":
                        action = request.POST.get("action")
                        if action=="profile":
                            profile_id=definitions.identifier(request.POST.get("profile"))
                            if profile_id not in {v["id"] for v in context["profiles"]}:
                                raise definitions.DefinitionError("활성 그룹을 선택하세요.")
                            cur.execute("""INSERT INTO gis.project_profile(project_id,profile_id,status,auto_assigned)
                                VALUES (%s,%s,'active',false) ON CONFLICT(project_id)
                                DO UPDATE SET profile_id=EXCLUDED.profile_id,status='active',auto_assigned=false,updated_at=now()""",
                                [str(project_id),profile_id])
                        elif action=="create":
                            feature_id=definitions.identifier(request.POST.get("feature"))
                            if feature_id not in feature_ids:
                                raise definitions.DefinitionError("프로젝트에서 허용하지 않는 시설물입니다.")
                            kind=request.POST.get("kind")
                            config=({"data_type":request.POST.get("data_type")} if kind=="scalar" else
                                    {"min_count":0,"max_count":int(request.POST.get("max_count",20))}
                                    if kind=="photo" else {})
                            item_id=definitions.add_item(cur,feature_id=feature_id,label=request.POST.get("label"),
                                kind=kind,config=config,project_id=project_id)
                            definitions.attach_project(cur,item_id=item_id,project_id=project_id)
                        elif action=="add":
                            item_id=definitions.identifier(request.POST.get("item"))
                            if item_id not in {v["id"] for v in available}:
                                raise definitions.DefinitionError("사용 가능한 항목이 아닙니다.")
                            definitions.attach_project(cur,item_id=item_id,project_id=project_id)
                        elif action=="remove":
                            item_id=definitions.identifier(request.POST.get("item"))
                            cur.execute("SELECT 1 FROM gis.profile_form_item WHERE profile_id=%s AND item_id=%s AND enabled",
                                        [plan["profile"]["id"],item_id])
                            if cur.fetchone():
                                raise definitions.DefinitionError("그룹에서 상속받은 항목은 제거할 수 없습니다.")
                            cur.execute("UPDATE gis.project_form_item SET enabled=false WHERE project_id=%s AND item_id=%s",
                                        [str(project_id),item_id])
                        else:
                            raise definitions.DefinitionError("지원하지 않는 요청입니다.")
                    context["definition"]=definitions.resolve(cur,project_id=project_id,
                        profile_id=plan["profile"]["id"],feature_ids=feature_ids)
                    context["available"]=available
        if request.method=="POST" and context["ready"]:
            return redirect("gis:project_form_configuration",project_id=project_id)
    except (definitions.DefinitionError,ValueError) as exc:
        context["error"]=str(exc) if isinstance(exc,definitions.DefinitionError) else "입력값을 확인하세요."
    except DatabaseError:
        logger.warning("GIS project form configuration failed")
        context["error"]="폼 구성을 저장하거나 읽지 못했습니다."
    return render(request,"geoflow_ops/gis/form_configuration.html",context,
                  status=400 if context.get("error") else 200)
