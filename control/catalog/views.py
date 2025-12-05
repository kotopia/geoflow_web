from uuid import uuid4
from django.db import connection, transaction
from django.http import JsonResponse
from django.contrib.auth.decorators import login_required
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib import messages
from django.urls import reverse
from urllib.parse import urlencode
from django.views.decorators.http import require_GET, require_http_methods, require_POST
from django.db.models import Max, Prefetch
import json
from .models import (
    CategoryNode, CategoryParent, CategoryFacet, CategoryFacetOption,
    CategoryOptionSet, CategoryOptionRule, CategoryOptionPick
)
from .forms import L1Form, L2Form, FacetForm, FacetOptionForm, OptionSetForm, OptionRuleForm


def _ok(data): return JsonResponse({'ok': True, 'results': data}, json_dumps_params={'ensure_ascii': False})
def _err(msg, status=400): return JsonResponse({'ok': False, 'error': msg}, status=status)

@login_required
def categories_board(request):
    l1_id = request.GET.get('l1')
    l2_id = request.GET.get('l2')

    # ── POST: 옵션 개별 pick 추가/삭제/초기화
    if request.method == "POST" and l2_id:
        l2_sel = get_object_or_404(CategoryNode, pk=l2_id, level=2)
        action   = request.POST.get("action")
        level_no = int(request.POST.get("level_no") or 0)

        # 이 Lv2에 연결된 facet(팩) 집합
        sets = CategoryOptionSet.objects.filter(l2=l2_sel).order_by('level_no','ord')
        facet_ids_lv3 = [s.facet_id for s in sets if s.level_no == 3]
        facet_ids_lv4 = [s.facet_id for s in sets if s.level_no == 4]

        def is_valid_option(opt_id: str) -> bool:
            facet_id = CategoryFacetOption.objects.filter(pk=opt_id).values_list('facet_id', flat=True).first()
            if not facet_id: return False
            return (facet_id in facet_ids_lv3) if level_no == 3 else (facet_id in facet_ids_lv4)

        if action == "add_pick" and level_no in (3,4):
            opt_id = request.POST.get("option_id")
            if opt_id and is_valid_option(opt_id):
                exists = CategoryOptionPick.objects.filter(l2=l2_sel, level_no=level_no, option_id=opt_id).exists()
                if not exists:
                    max_ord = CategoryOptionPick.objects.filter(l2=l2_sel, level_no=level_no).aggregate(m=Max("ord"))["m"] or 0
                    CategoryOptionPick.objects.create(l2=l2_sel, level_no=level_no, option_id=opt_id, ord=max_ord+1)

        elif action == "del_pick":
            pick_id = request.POST.get("pick_id")
            if pick_id:
                CategoryOptionPick.objects.filter(id=pick_id, l2=l2_sel).delete()

        elif action == "clear_picks" and level_no in (3,4):
            CategoryOptionPick.objects.filter(l2=l2_sel, level_no=level_no).delete()

        # PRG
        return redirect(f"{reverse('catalog:categories_board')}?l1={l1_id or ''}&l2={l2_id or ''}")

    # ── GET: 렌더
    l1_list = CategoryNode.objects.filter(level=1, active=True).order_by('ord','name')
    l1_sel = get_object_or_404(CategoryNode, pk=l1_id, level=1) if l1_id else None

    if l1_sel:
        child_ids = CategoryParent.objects.filter(parent=l1_sel).values_list('child_id', flat=True)
        l2_list = CategoryNode.objects.filter(id__in=child_ids, level=2, active=True).order_by('ord','name')
    else:
        l2_list = CategoryNode.objects.none()

    l2_sel = get_object_or_404(CategoryNode, pk=l2_id, level=2) if l2_id else None

    facet3 = facet4 = None
    picks3 = picks4 = []
    eff_opts3 = eff_opts4 = []   # 실제 사용 옵션(픽이 없으면 전체 옵션)
    add_candidates3 = add_candidates4 = []  # 추가 가능 후보

    rules_count = 0
    sets_lv3 = sets_lv4 = []

    if l2_sel:
        sets = (CategoryOptionSet.objects
                .filter(l2=l2_sel)
                .select_related('facet')
                .order_by('level_no','ord','facet__name'))
        sets_lv3 = [s for s in sets if s.level_no == 3]
        sets_lv4 = [s for s in sets if s.level_no == 4]
        facet_ids_lv3 = [s.facet_id for s in sets_lv3]
        facet_ids_lv4 = [s.facet_id for s in sets_lv4]

        # 연결된 팩에서 뽑을 수 있는 전체 옵션(기본 후보)
        all_lv3_opts = CategoryFacetOption.objects.filter(facet_id__in=facet_ids_lv3, active=True).order_by('ord','name')
        all_lv4_opts = CategoryFacetOption.objects.filter(facet_id__in=facet_ids_lv4, active=True).order_by('ord','name')

        # 현재 pick
        picks3 = list(CategoryOptionPick.objects.filter(l2=l2_sel, level_no=3).select_related('option').order_by('ord','option__name'))
        picks4 = list(CategoryOptionPick.objects.filter(l2=l2_sel, level_no=4).select_related('option').order_by('ord','option__name'))

        # 실제 사용 옵션(픽이 있으면 pick만, 없으면 전체)
        if picks3:
            eff_opts3 = [p.option for p in picks3]
            add_candidates3 = all_lv3_opts.exclude(id__in=[p.option_id for p in picks3])
        else:
            eff_opts3 = list(all_lv3_opts)
            add_candidates3 = all_lv3_opts  # '부분선택 모드'로 바꾸고 싶을 때 고르는 초기 후보

        if picks4:
            eff_opts4 = [p.option for p in picks4]
            add_candidates4 = all_lv4_opts.exclude(id__in=[p.option_id for p in picks4])
        else:
            eff_opts4 = list(all_lv4_opts)
            add_candidates4 = all_lv4_opts

        rules_count = CategoryOptionRule.objects.filter(l2=l2_sel, active=True).count()

    ctx = dict(
        l1_list=l1_list, l1_sel=l1_sel,
        l2_list=l2_list, l2_sel=l2_sel,
        sets_lv3=sets_lv3, sets_lv4=sets_lv4,
        eff_opts3=eff_opts3, eff_opts4=eff_opts4,
        picks3=picks3, picks4=picks4,
        add_candidates3=add_candidates3, add_candidates4=add_candidates4,
        rules_count=rules_count,
    )
    return render(request, 'catalog/categories_board.html', ctx)

# ─────────────────────────────────────────────
# L1(대분류) 관리

@require_http_methods(["GET", "POST"])
def l1_admin_create(request):
    if request.method == 'POST':
        form = L1Form(request.POST)
        if form.is_valid():
            obj = form.save(commit=False)
            obj.level = 1   # 고정
            obj.save()
            messages.success(request, '대분류가 추가되었습니다.')
            return redirect('catalog:categories_board')
        messages.error(request, '입력값을 확인하세요.')
    else:
        # 기본 정렬값 제안(마지막 ord + 1)
        last = CategoryNode.objects.filter(level=1).order_by('-ord').first()
        init = {'ord': (last.ord + 1) if last else 1, 'active': True}
        form = L1Form(initial=init)
    return render(request, 'catalog/l1_form.html', {'form': form, 'mode': 'create'})

@require_http_methods(["GET", "POST"])
def l1_admin_update(request, pk):
    obj = get_object_or_404(CategoryNode, pk=pk, level=1)
    if request.method == 'POST':
        form = L1Form(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, '대분류가 수정되었습니다.')
            return redirect('catalog:categories_board')
        messages.error(request, '입력값을 확인하세요.')
    else:
        form = L1Form(instance=obj)
    return render(request, 'catalog/l1_form.html', {'form': form, 'mode': 'edit'})

@require_POST
def l1_admin_delete(request, pk):
    obj = get_object_or_404(CategoryNode, pk=pk, level=1)
    obj.delete()
    messages.success(request, '대분류가 삭제되었습니다.')
    return redirect('catalog:categories_board')

# ─────────────────────────────────────────────
# L2(중분류) 관리

# L2 목록
def node_admin_list(request):
    l2s = CategoryNode.objects.filter(level=2, active=True).order_by('ord','name')
    return render(request, 'catalog/node_list.html', {'items': l2s})

# 특정 L2에 붙은 옵션팩(L3/L4) 관리
def node_link_admin(request, node_id):
    l2 = get_object_or_404(CategoryNode, pk=node_id, level=2)
    sets = (CategoryOptionSet.objects
            .filter(l2=l2)
            .select_related('facet')
            .order_by('level_no','ord','facet__name'))
    # 선택용 Facet 풀(중복방지: 이미 붙은 건 제외)
    used = sets.values_list('facet_id', 'level_no')
    used_facet_ids_lvl3 = [fid for fid, lv in used if lv == 3]
    used_facet_ids_lvl4 = [fid for fid, lv in used if lv == 4]
    facets3 = CategoryFacet.objects.exclude(id__in=used_facet_ids_lvl3).order_by('ord','name')
    facets4 = CategoryFacet.objects.exclude(id__in=used_facet_ids_lvl4).order_by('ord','name')
    return render(request, 'catalog/node_links.html', {
        'l2': l2, 'sets': sets, 'facets3': facets3, 'facets4': facets4
    })

@require_http_methods(["GET", "POST"])
def l2_admin_create(request):
    """선택된 L1 하위에 Lv2를 하나 만든다."""
    l1_id = request.GET.get('l1') or request.POST.get('l1')
    l1 = get_object_or_404(CategoryNode, pk=l1_id, level=1)

    if request.method == 'POST':
        form = L2Form(request.POST)
        if form.is_valid():
            with transaction.atomic():
                obj: CategoryNode = form.save(commit=False)
                obj.id = obj.id or uuid4()      # 안전망
                obj.level = 2
                obj.save()                      # Node 저장
                # L1-L2 링크
                CategoryParent.objects.create(parent=l1, child=obj)
            messages.success(request, '중분류가 추가되었습니다.')
            return redirect(f"{reverse('catalog:categories_board')}?l1={l1.id}&l2={obj.id}")
        messages.error(request, '입력값을 확인하세요.')
    else:
        last = CategoryNode.objects.filter(level=2).order_by('-ord').first()
        init = {'ord': (last.ord + 1) if last else 1, 'active': True}
        form = L2Form(initial=init)
    return render(request, 'catalog/l2_form.html', {'form': form, 'l1': l1, 'mode': 'create'})

@require_http_methods(["GET", "POST"])
def l2_admin_update(request, pk):
    """Lv2(중분류) 수정"""
    l2 = get_object_or_404(CategoryNode, pk=pk, level=2)

    # 보드에서 돌아오기용 파라미터
    from_board = request.GET.get('from') == 'board' or request.POST.get('from') == 'board'
    l1_id = request.GET.get('l1') or request.POST.get('l1')

    if request.method == 'POST':
        form = L2Form(request.POST, instance=l2)
        if form.is_valid():
            form.save()
            messages.success(request, '중분류가 수정되었습니다.')
            if from_board and l1_id:
                qs = urlencode({'l1': l1_id, 'l2': str(l2.id)})
                return redirect(f"{reverse('catalog:categories_board')}?{qs}")
            return redirect('catalog:node_admin_list')
        messages.error(request, '입력값을 확인하세요.')
    else:
        form = L2Form(instance=l2)

    # 선택된 L2의 상위 L1을 찾아 템플릿에 전달(헤더 표기/복귀 링크 구성)
    parent_l1_id = (CategoryParent.objects
                    .filter(child=l2)
                    .order_by('parent_id')
                    .values_list('parent_id', flat=True)
                    .first())
    l1 = CategoryNode.objects.filter(pk=parent_l1_id, level=1).first()
    return render(request, 'catalog/l2_form.html', {
        'form': form,
        'l1': l1,
        'mode': 'edit',
    })

# ========= Lv2 삭제 =========
@require_POST
@transaction.atomic
def l2_admin_delete(request, pk):
    """Lv2와 그에 달린 연결/규칙/픽 삭제 후 Lv2 삭제"""
    l2 = get_object_or_404(CategoryNode, pk=pk, level=2)
    # 연결/규칙/픽 정리
    CategoryOptionRule.objects.filter(l2=l2).delete()
    CategoryOptionSet.objects.filter(l2=l2).delete()
    CategoryOptionPick.objects.filter(l2=l2).delete()
    CategoryParent.objects.filter(child=l2).delete()
    l1_id = request.POST.get('l1')  # 보드로 돌아가기용
    l2.delete()
    messages.success(request, '중분류가 삭제되었습니다.')
    return redirect(f"{reverse('catalog:categories_board')}?l1={l1_id or ''}")

# ========= OptionSet 생성 뷰 보완 (id/ord 자동) =========
@require_http_methods(["GET", "POST"])
def option_set_create(request, node_id):
    l2 = get_object_or_404(CategoryNode, pk=node_id, level=2)
    if request.method == 'POST':
        form = OptionSetForm(request.POST)
        if form.is_valid():
            obj: CategoryOptionSet = form.save(commit=False)
            obj.id = obj.id or uuid4()  # ✅ id 기본값 보장
            # ord 자동
            last = CategoryOptionSet.objects.filter(l2=obj.l2, level_no=obj.level_no).order_by('-ord').first()
            obj.ord = obj.ord or ((last.ord + 1) if last else 1)
            obj.save()
            messages.success(request, '옵션팩이 연결되었습니다.')
            return redirect(reverse('catalog:node_link_admin', args=[l2.id]))
        messages.error(request, '입력값을 확인하세요.')
    else:
        last = CategoryOptionSet.objects.filter(l2=l2).order_by('-ord').first()
        init = {'l2': l2, 'ord': (last.ord + 1) if last else 1}
        form = OptionSetForm(initial=init)
    return render(request, 'catalog/option_set_form.html', {'form': form, 'l2': l2})

def option_set_delete(request, set_id):
    obj = get_object_or_404(CategoryOptionSet, pk=set_id)
    node_id = obj.l2_id
    obj.delete()
    return redirect(reverse('catalog:node_link_admin', args=[node_id]))

# 규칙 목록/추가/삭제
def option_rule_list(request, node_id):
    l2 = get_object_or_404(CategoryNode, pk=node_id, level=2)
    rules = (CategoryOptionRule.objects
             .filter(l2=l2, active=True)
             .select_related('facet3_opt','facet3_opt__facet','facet4_opt','facet4_opt__facet')
             .order_by('facet3_opt__facet__ord','facet3_opt__ord','facet4_opt__ord'))
    return render(request, 'catalog/option_rule_list.html', {'l2': l2, 'rules': rules})

def option_rule_create(request, node_id):
    l2 = get_object_or_404(CategoryNode, pk=node_id, level=2)
    if request.method == 'POST':
        form = OptionRuleForm(request.POST, l2=l2)
        if form.is_valid():
            form.save()
            return redirect(reverse('option_rule_list', args=[l2.id]))
    else:
        form = OptionRuleForm(initial={'l2': l2}, l2=l2)
    return render(request, 'catalog/option_rule_form.html', {'form': form, 'l2': l2})

def option_rule_delete(request, rule_id):
    obj = get_object_or_404(CategoryOptionRule, pk=rule_id)
    node_id = obj.l2_id
    obj.delete()
    return redirect(reverse('option_rule_list', args=[node_id]))


# ─────────────────────────────────────────────
# 옵션팩(L3/L4)연결

def _ok(results=None, **extra):
    payload = {'ok': True}
    if results is not None:
        payload['results'] = results
    payload.update(extra)
    return JsonResponse(payload, json_dumps_params={'ensure_ascii': False})

def _err(msg, status=400):
    return JsonResponse({'ok': False, 'error': msg}, status=status, json_dumps_params={'ensure_ascii': False})

@require_GET
def rules_matrix(request, node_id):
    """
    선택한 L2 기준으로:
      - 연결된 L3/L4 옵션팩 1쌍(각 1개) 선택
      - 각 옵션팩의 옵션 목록
      - 현재 허용된 (L3옵션, L4옵션) 페어 리스트
    를 JSON으로 반환
    """
    l2 = get_object_or_404(CategoryNode, pk=node_id, level=2)

    # 연결된 L3/L4 옵션팩 조회
    sets = (CategoryOptionSet.objects
            .filter(l2=l2)
            .select_related('facet')
            .order_by('level_no', 'ord', 'facet__name'))
    facet3 = next((s.facet for s in sets if s.level_no == 3), None)
    facet4 = next((s.facet for s in sets if s.level_no == 4), None)

    if not (facet3 and facet4):
        return JsonResponse({
            'ok': True,
            'l3_facet': None, 'l4_facet': None,
            'l3_options': [], 'l4_options': [],
            'allowed': [],
            'message': 'L3/L4 옵션팩이 모두 연결되어 있어야 규칙을 설정할 수 있습니다.'
        }, json_dumps_params={'ensure_ascii': False})

    l3_opts = list(CategoryFacetOption.objects
                   .filter(facet=facet3, active=True)
                   .order_by('ord', 'name')
                   .values('id', 'code', 'name'))
    l4_opts = list(CategoryFacetOption.objects
                   .filter(facet=facet4, active=True)
                   .order_by('ord', 'name')
                   .values('id', 'code', 'name'))

    rules = list(CategoryOptionRule.objects
                 .filter(l2=l2, active=True)
                 .values_list('facet3_opt_id', 'facet4_opt_id'))

    return JsonResponse({
        'ok': True,
        'l3_facet': {'id': str(facet3.id), 'code': facet3.code, 'name': facet3.name},
        'l4_facet': {'id': str(facet4.id), 'code': facet4.code, 'name': facet4.name},
        'l3_options': [{'id': str(x['id']), 'code': x['code'], 'name': x['name']} for x in l3_opts],
        'l4_options': [{'id': str(x['id']), 'code': x['code'], 'name': x['name']} for x in l4_opts],
        'allowed': [[str(a), str(b)] for (a, b) in rules]
    }, json_dumps_params={'ensure_ascii': False})

@require_http_methods(["POST"])
@transaction.atomic
def rules_matrix_patch(request, node_id):
    """
    요청 바디(JSON):
      {
        "allow":    [ [l3_opt_id, l4_opt_id], ... ],
        "disallow": [ [l3_opt_id, l4_opt_id], ... ]
      }
    allow  : 규칙 없으면 생성(active=True), 비활성화돼 있으면 활성화
    disallow: 해당 규칙 삭제(또는 active=False로 바꾸고 싶다면 여기서 변경)
    """
    l2 = get_object_or_404(CategoryNode, pk=node_id, level=2)
    try:
        payload = json.loads(request.body or '{}')
    except json.JSONDecodeError:
        return _err('잘못된 JSON', 400)

    allow_list = payload.get('allow', []) or []
    disallow_list = payload.get('disallow', []) or []

    # L3/L4 옵션팩(각 1개) 확인
    sets = CategoryOptionSet.objects.filter(l2=l2).select_related('facet')
    facet3 = next((s.facet for s in sets if s.level_no == 3), None)
    facet4 = next((s.facet for s in sets if s.level_no == 4), None)
    if not (facet3 and facet4):
        return _err('L3/L4 옵션팩이 모두 연결되어 있어야 합니다.', 400)

    # 허용: upsert
    for l3_id, l4_id in allow_list:
        obj, created = CategoryOptionRule.objects.get_or_create(
            l2=l2,
            facet3_opt_id=l3_id,
            facet4_opt_id=l4_id,
            defaults={'active': True}
        )
        if not created and not obj.active:
            obj.active = True
            obj.save(update_fields=['active'])

    # 비허용: delete
    if disallow_list:
        CategoryOptionRule.objects.filter(
            l2=l2,
            facet3_opt_id__in=[a for a, _ in disallow_list],
            facet4_opt_id__in=[b for _, b in disallow_list]
        ).delete()

    return _ok({'updated': True})

# ─────────────────────────────────────────────
# 옵션 목록

@require_GET
def facet_options(request):
    facet_code = request.GET.get('facet_code'); facet_id = request.GET.get('facet_id')
    if not (facet_code or facet_id): return _err('facet_code 또는 facet_id 필요')
    try:
        facet = CategoryFacet.objects.get(**({'code': facet_code} if facet_code else {'id': facet_id}), active=True)
    except CategoryFacet.DoesNotExist: return _err('옵션팩 없음', 404)
    rows = CategoryFacetOption.objects.filter(facet=facet, active=True).order_by('ord', 'name')
    data = [{'id': str(o.id), 'code': o.code, 'name': o.name, 'ord': o.ord,
             'default_unit': o.default_unit, 'geom_hint': o.geom_hint} for o in rows]
    return _ok(data)

def facet_admin_list(request):
    qs = CategoryFacet.objects.all().order_by('ord', 'name')
    return render(request, 'catalog/facet_list.html', {'items': qs})

@login_required
def facet_admin_create(request):
    if request.method == 'POST':
        form = FacetForm(request.POST)
        next_url = request.POST.get('next') or request.GET.get('next')
        if form.is_valid():
            obj = form.save()
            # ✅ next가 오면 그쪽으로, 없으면 기본 목록으로
            if next_url:
                return redirect(next_url)
            return redirect('catalog:facet_admin_list')
    else:
        form = FacetForm()
    return render(request, 'catalog/facet_form.html', {'form': form, 'mode': 'create'})

@require_http_methods(["GET", "POST"])
def facet_admin_update(request, pk):
    obj = get_object_or_404(CategoryFacet, pk=pk)
    if request.method == "POST":
        form = FacetForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "옵션팩이 수정되었습니다.")
            return redirect('facet_admin_list')
        messages.error(request, "입력값을 확인하세요.")
    else:
        form = FacetForm(instance=obj)
    return render(request, 'catalog/facet_form.html', {'form': form, 'mode': 'edit'})

@require_POST
def facet_admin_delete(request, pk):
    obj = get_object_or_404(CategoryFacet, pk=pk)
    obj.delete()
    messages.success(request, "옵션팩을 삭제했습니다.")
    return redirect('facet_admin_list')

# ─────────────────────────────────────────────
# 옵션 목록
def option_admin_list(request, facet_id):
    facet = get_object_or_404(CategoryFacet, pk=facet_id)
    qs = CategoryFacetOption.objects.filter(facet=facet).order_by('ord', 'name')
    ctx = {'facet': facet, 'items': qs}
    return render(request, 'catalog/option_list.html', ctx)

# 옵션 추가
@require_http_methods(["GET","POST"])
def option_admin_create(request, facet_id):
    facet = get_object_or_404(CategoryFacet, pk=facet_id)
    if request.method == 'POST':
        form = FacetOptionForm(request.POST, facet=facet)
        if form.is_valid():
            form.save()
            messages.success(request, '옵션이 추가되었습니다.')
            return redirect('catalog:option_admin_list', facet_id=facet.id)
        messages.error(request, '입력값을 확인하세요.')
    else:
        # 기본 정렬값 제안(마지막 ord + 1)
        last = CategoryFacetOption.objects.filter(facet=facet).order_by('-ord').first()
        init = {'ord': (last.ord + 1) if last else 1, 'active': True}
        form = FacetOptionForm(initial=init, facet=facet)
    return render(request, 'catalog/option_form.html', {'form': form, 'mode':'create', 'facet': facet})

# 옵션 수정
@require_http_methods(["GET","POST"])
def option_admin_update(request, pk):
    obj = get_object_or_404(CategoryFacetOption, pk=pk)
    if request.method == 'POST':
        form = FacetOptionForm(request.POST, instance=obj, facet=obj.facet)
        if form.is_valid():
            form.save()
            messages.success(request, '옵션이 수정되었습니다.')
            return redirect('catalog:option_admin_list', facet_id=obj.facet_id)
        messages.error(request, '입력값을 확인하세요.')
    else:
        form = FacetOptionForm(instance=obj, facet=obj.facet)
    return render(request, 'catalog/option_form.html', {'form': form, 'mode':'edit', 'facet': obj.facet})

# 옵션 삭제
@require_POST
def option_admin_delete(request, pk):
    obj = get_object_or_404(CategoryFacetOption, pk=pk)
    facet_id = obj.facet_id
    obj.delete()
    messages.success(request, '옵션을 삭제했습니다.')
    return redirect('catalog:option_admin_list', facet_id=facet_id)