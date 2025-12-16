import json

# 중앙 카탈로그 헬퍼 불러오기
from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.http import JsonResponse
from control.gf_authz.permissions import gf_perm_required
from django.views.decorators.http import require_POST, require_GET

# ── 멀티테넌트 alias 헬퍼 (views_projects와 동일한 방식)
from control.middleware import current_db_alias
def _alias(request):
    return current_db_alias()

# ── 모델/서비스/유틸
from .models import Project, ProjectScopeItem
from control.catalog.models import CategoryNode, CategoryFacetOption, CategoryParent
from control.catalog import services_tenant as cat_svc
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from typing import Any, Dict, List, Set


@login_required
def catalog_board(request):
    """
    테넌트가 사용하는 카테고리 설정 화면
    - 왼쪽: L1 목록
    - 오른쪽: 선택된 L1에 대한 L2 + Lv3/Lv4 옵션 보드
    """
    # 1) 현재 테넌트 DB alias (미들웨어에서 세션에 넣어줌)
    tenant_alias = request.session.get(
        "tenant_db_alias",
        getattr(settings, "DEFAULT_TENANT_DB_ALIAS", "cheonan_db"),
    )

    # 2) 프로젝트 ID (지금은 GET 파라미터로 받도록)
    project_id = request.GET.get("project_id")  # 나중에 현재 프로젝트 context에서 가져오면 됨

    # 3) 중앙 L1 목록 읽기
    l1_list = cat_svc.fetch_l1_list()

    if not l1_list:
        # 아직 카탈로그가 하나도 없을 때
        ctx = {
            "l1_list": [],
            "current_l1": None,
            "panel": None,
            "project_id": project_id,
        }
        return render(request, "geoflow_ops/catalog/catalog_board.html", ctx)

    # 4) 선택된 L1 결정 (GET ?l1=... 없으면 첫 번째 L1 사용)
    l1_id = request.GET.get("l1")
    if not l1_id:
        l1_id = l1_list[0].id  # DTO의 id (문자열)

    # 5) 선택된 L1 기준으로 L2 + 옵션 패널 데이터 구성
    panel = cat_svc.build_l2_panel_data(
        tenant_alias=tenant_alias,
        l1_id=l1_id,
        project_id=project_id,
    )

    # 6) 템플릿 컨텍스트
    current_l1 = next((x for x in l1_list if x.id == l1_id), None)

    ctx = {
        "l1_list": l1_list,
        "current_l1": current_l1,
        "panel": panel,
        "project_id": project_id,
    }
    return render(request, "geoflow_ops/catalog/catalog_board.html", ctx)

@login_required
@gf_perm_required("projects.edit")
def project_scope_modal(request, pk):
    """
    프로젝트 업무범위 모달
    - 좌측: L1/L2 트리
    - 우측: 선택된 L2의 L3 옵션만 표로 표시
    """
    alias = _alias(request)
    project = get_object_or_404(Project.objects.using(alias), pk=pk)

    # 1) 중앙 L1 목록
    l1_list = cat_svc.fetch_l1_list()

    current_l1_id = request.GET.get("l1")
    if not current_l1_id and l1_list:
        current_l1_id = l1_list[0].id  # NodeDTO.id (문자열)

    panel = None
    current_l2_id = request.GET.get("l2")
    table_rows = []
    selected_l2 = None

    # 2) 선택된 L1에 대한 L2/L3 정보 + scope_item 조합
    if current_l1_id:
        panel = cat_svc.build_l2_panel_data(
            tenant_alias=alias,
            l1_id=current_l1_id,
            project_id=str(pk),
        )

        # 이 프로젝트의 기존 scope_item (L2+L3 기준, L4는 아직 사용 안 함)
        scope_qs = ProjectScopeItem.objects.using(alias).filter(
            project_id=pk,
            lv4_id__isnull=True,
        )
        scope_by_l2_lv3: Dict[tuple, ProjectScopeItem] = {}
        for s in scope_qs:
            key = (str(s.lv2_id), str(s.lv3_id) if s.lv3_id else None)
            scope_by_l2_lv3[key] = s

        # L2 목록 중에서 current_l2_id 결정
        l2_items = panel["l2"] if panel else []
        if l2_items:
            if not current_l2_id:
                current_l2_id = str(l2_items[0]["node"].id)

            # 선택된 L2 하나에 대해서만 L3 옵션 + scope 묶어서 table_rows 생성
            for row in l2_items:
                node = row["node"]  # L2 NodeDTO
                l2_id = str(node.id)
                if l2_id != current_l2_id:
                    continue

                selected_l2 = node
                opts3 = row["options"].get(3, []) if row.get("options") else []
                for opt3 in opts3:
                    key = (l2_id, opt3.id)
                    existing = scope_by_l2_lv3.get(key)

                    if existing:
                        unit_value = (existing.unit or opt3.default_unit or "")
                        design_display = format_qty(existing.design_qty)
                        completed_display = format_qty(existing.completed_qty)
                    else:
                        unit_value = opt3.default_unit or ""
                        design_display = ""
                        completed_display = ""

                    table_rows.append({
                        "l2": node,
                        "opt3": opt3,
                        "existing": existing,
                        "unit_value": unit_value,
                        "design_display": design_display,
                        "completed_display": completed_display,
                    })
    context = {
        "project": project,
        "l1_list": l1_list,
        "current_l1_id": current_l1_id,
        "current_l2_id": current_l2_id,
        "selected_l2": selected_l2,
        "panel": panel,
        "table_rows": table_rows,
    }
    return render(request, "geoflow_ops/projects/project_scope_modal.html", context)

@require_GET
@login_required
@gf_perm_required("projects.edit")
def project_scope_data(request, pk):
    """
    모달 오픈 시 1회 호출:
    - 중앙 카탈로그 L1→L2→(L3) 전체
    - 현재 프로젝트의 선택/수량 상태
    를 JSON 한 번에 내려준다.
    """
    alias = _alias(request)
    project = get_object_or_404(Project.objects.using(alias), pk=pk)

    # 1) 중앙 L1 목록
    l1_nodes = cat_svc.fetch_l1_list()  # NodeDTO 리스트 (id, code, name, ord)
    l1_list = [{"id": x.id, "code": x.code, "name": x.name, "ord": getattr(x, "ord", 0)} for x in l1_nodes]

    # 2) L1별 L2 + L2별 L3 수집
    l2_by_l1 = {}
    l3_by_l2 = {}
    for l1 in l1_nodes:
        panel = cat_svc.build_l2_panel_data(
            tenant_alias=alias, l1_id=l1.id, project_id=str(pk)
        )
        l2_items = panel.get("l2") or []
        l2_list = []
        for row in l2_items:
            node = row["node"]  # L2 NodeDTO
            l2_list.append({"id": node.id, "code": node.code, "name": node.name, "ord": getattr(node, "ord", 0)})

            # 이 L2의 L3 옵션들
            opts3 = (row.get("options") or {}).get(3, [])  # FacetOptionDTO(id, code, name, default_unit, ord)
            l3_list = []
            for opt in opts3:
                l3_list.append({
                    "id": opt.id,
                    "code": opt.code,
                    "name": opt.name,
                    "unit_def": getattr(opt, "default_unit", "") or "",
                    "ord": getattr(opt, "ord", 0),
                })
            l3_by_l2[str(node.id)] = l3_list
        l2_by_l1[str(l1.id)] = l2_list

    # 3) 현재 프로젝트의 선택/수량(테넌트 DB) -> (l2|l3) 맵
    items = ProjectScopeItem.objects.using(alias).filter(project_id=project.pk, lv4_id__isnull=True)
    project_items = {}
    for it in items:
        key = f"{it.lv2_id}|{it.lv3_id}"
        project_items[key] = {
            "active": True,
            "unit": it.unit or "",
            "design_qty": "" if it.design_qty is None else str(it.design_qty),
            "completed_qty": "" if it.completed_qty is None else str(it.completed_qty),
        }

    # 4) 버전(중앙 최신 개정 시각 등). 지금은 간단히 v1
    version = "v1"

    return JsonResponse({
        "version": version,
        "l1_list": sorted(l1_list, key=lambda x: (x["ord"], x["name"])),
        "l2_by_l1": l2_by_l1,
        "l3_by_l2": l3_by_l2,
        "project_items": project_items,
    })


@login_required
@gf_perm_required("projects.edit")
@require_POST
def project_scope_save(request, pk):
    alias = _alias(request)

    # 1) JSON 시도
    payload = None
    try:
        payload = json.loads(request.body.decode("utf-8") or "{}")
    except Exception:
        payload = None

    # 2) 폼 대안(items=<json string>)도 허용
    if payload is None or "items" not in payload:
        items_str = request.POST.get("items")
        if items_str:
            try:
                payload = {"items": json.loads(items_str)}
            except Exception:
                return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    if not payload:
        return JsonResponse({"ok": False, "error": "invalid_json"}, status=400)

    items = payload.get("items") or []
    if not isinstance(items, list):
        return JsonResponse({"ok": False, "error": "invalid_items"}, status=400)

    project = get_object_or_404(Project.objects.using(alias), pk=pk)

    def parse_decimal(val):
        if val in (None, "", "null"):
            return None
        try:
            return Decimal(str(val))
        except (InvalidOperation, TypeError, ValueError):
            return None

    for row in items:
        lv2_id = row.get("lv2_id")
        lv3_id = row.get("lv3_id")
        if not lv2_id or not lv3_id:
            continue

        active = bool(row.get("active"))
        unit = (row.get("unit") or "").strip()
        design_qty = parse_decimal(row.get("design_qty"))
        completed_qty = parse_decimal(row.get("completed_qty"))

        base_filter = {
            "project_id": project.pk,
            "lv2_id": lv2_id,
            "lv3_id": lv3_id,
            "lv4_id": None,
        }

        if not active:
            # OFF면 해당 레코드 제거(있으면)
            ProjectScopeItem.objects.using(alias).filter(**base_filter).delete()
            continue

        if not unit:
            unit = "EA"

        defaults = {
            "unit": unit,
            "design_qty": design_qty,
            "completed_qty": completed_qty,
        }
        ProjectScopeItem.objects.using(alias).update_or_create(
            **base_filter,
            defaults=defaults,
        )

    return JsonResponse({"ok": True})

def project_scope_summary(request, pk):
    alias = _alias(request)
    prj = get_object_or_404(Project.objects.using(alias)
                            .select_related("contract"), pk=pk)
    # 기존 project_detail의 scope_groups 구성 로직을 재사용/함수화해서 가져오기
    scope_groups = build_scope_groups(alias, prj.pk)  # <- 기존 로직 함수화 가정
    return render(request, "geoflow_ops/projects/_scope_summary.html", {
        "project": prj,
        "scope_groups": scope_groups,
    })

# ── 수량 표시 규칙 (views_projects와 동일)
def format_qty(val):
    if val in (None, ""):
        return ""
    try:
        d = val if isinstance(val, Decimal) else Decimal(str(val))
    except (InvalidOperation, TypeError, ValueError):
        return ""
    d = d.quantize(Decimal("0.001"), rounding=ROUND_HALF_UP)
    if d == d.to_integral():
        return str(d.to_integral())
    s = format(d, "f")
    s = s.rstrip("0").rstrip(".")
    return s

# ── 스코프 요약(L1→L2→행) 생성 (project_detail의 그룹핑 로직을 함수화)
def build_scope_groups(tenant_alias: str, project_id) -> List[Dict[str, Any]]:
    scope_qs = ProjectScopeItem.objects.using(tenant_alias).filter(
        project_id=project_id, lv3_id__isnull=False, lv4_id__isnull=True
    )
    scope_items = list(scope_qs)
    if not scope_items:
        return []

    lv2_ids = {s.lv2_id for s in scope_items}
    lv3_ids = {s.lv3_id for s in scope_items}
    central = cat_svc.CENTRAL_ALIAS

    l2_nodes = list(CategoryNode.objects.using(central).filter(id__in=lv2_ids))
    l2_map = {str(n.id): n for n in l2_nodes}

    parents = list(CategoryParent.objects.using(central).filter(child_id__in=lv2_ids))
    child_to_parent: Dict[str, str] = {}
    l1_ids: Set[Any] = set()
    for p in parents:
        child_to_parent[str(p.child_id)] = str(p.parent_id)
        l1_ids.add(p.parent_id)

    l1_nodes = list(CategoryNode.objects.using(central).filter(id__in=l1_ids))
    l1_map = {str(n.id): n for n in l1_nodes}

    l3_nodes = list(CategoryFacetOption.objects.using(central).filter(id__in=lv3_ids))
    l3_map = {str(o.id): o for o in l3_nodes}

    from collections import defaultdict
    grouped: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    for s in scope_items:
        l2_id = str(s.lv2_id); l3_id = str(s.lv3_id)
        l2 = l2_map.get(l2_id); l3 = l3_map.get(l3_id)
        if not l2 or not l3: 
            continue
        l1_id = child_to_parent.get(l2_id)
        if not l1_id:
            continue
        grouped[l1_id][l2_id].append({
            "l3_name": l3.name, "l3_code": l3.code,
            "unit": s.unit,
            "design_qty": s.design_qty, "completed_qty": s.completed_qty,
            "design_display": format_qty(s.design_qty),
            "completed_display": format_qty(s.completed_qty),
        })

    scope_groups: List[Dict[str, Any]] = []
    sorted_l1 = sorted(l1_nodes, key=lambda n: (n.ord, n.name))
    l2_by_id = {str(n.id): n for n in l2_nodes}
    for l1 in sorted_l1:
        l1_id = str(l1.id)
        if l1_id not in grouped:
            continue
        l2_dict = grouped[l1_id]
        l2_blocks: List[Dict[str, Any]] = []
        l2_ids_for_l1 = [lid for lid in l2_dict.keys() if lid in l2_by_id]
        sorted_l2 = sorted((l2_by_id[lid] for lid in l2_ids_for_l1), key=lambda n: (n.ord, n.name))
        for l2 in sorted_l2:
            rows = l2_dict.get(str(l2.id)) or []
            if rows:
                l2_blocks.append({"l2_name": l2.name, "l2_code": l2.code, "rows": rows})
        if l2_blocks:
            scope_groups.append({"l1_name": l1.name, "l1_code": l1.code, "l2_blocks": l2_blocks})
    return scope_groups
