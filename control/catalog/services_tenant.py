# control/catalog/services_tenant.py
# -*- coding: utf-8 -*-
"""
중앙 카탈로그(읽기) + 테넌트 선택/비활성(쓰기) 조합 헬퍼
- 중앙은 항상 CENTRAL_ALIAS(= settings.CENTRAL_DB_ALIAS)로 조회
- 테넌트/프로젝트 선택/비활성은 tenant_alias(세션에서 가져온 별칭)에서 조회
"""

from dataclasses import dataclass
from typing import List, Optional, Tuple, Dict, Set

from django.conf import settings

# ─────────────────────────────────────────────────────────────────────────────
# 1) 중앙 DB alias
CENTRAL_ALIAS = getattr(settings, "CENTRAL_DB_ALIAS", "default")

# ─────────────────────────────────────────────────────────────────────────────
# 2) 중앙 모델 import (control.catalog.models)
from .models import (
    CategoryNode,
    CategoryParent,
    CategoryOptionSet,
    CategoryFacet,
    CategoryFacetOption,
    CategoryOptionRule,
    CategoryOptionPick,
)

# ─────────────────────────────────────────────────────────────────────────────
# 3) (예시) 테넌트 선택/비활성 모델
#    실제 앱 위치/필드명이 다르면 이 주석을 참고해서 맞춰주세요.
#
# from geoflow_ops.tenant_models import TenantL1L2Selection, TenantOptionDisable
#
# class TenantL1L2Selection(models.Model):
#     project_id = models.UUIDField(null=True, blank=True)   # 프로젝트별 관리 원하면 사용
#     node_id    = models.UUIDField()                        # L1 또는 L2(CategoryNode.id)
#     selected   = models.BooleanField(default=True)
#     class Meta:
#         managed = False
#         db_table = 'tenant_l1l2_selection'
#
# class TenantOptionDisable(models.Model):
#     project_id = models.UUIDField(null=True, blank=True)
#     l2_id      = models.UUIDField()                        # L2(CategoryNode.id)
#     level_no   = models.SmallIntegerField()                # 3 or 4
#     option_id  = models.UUIDField()                        # CategoryFacetOption.id
#     class Meta:
#         managed = False
#         db_table = 'tenant_option_disable'


# ─────────────────────────────────────────────────────────────────────────────
# 4) 반환용 DTO (level은 헬퍼가 직접 1/2로 채움)
@dataclass(frozen=True)
class NodeDTO:
    id: str
    code: str
    name: str
    ord: int
    active: bool
    level: int  # 1 또는 2 (DB 컬럼이 아니라 헬퍼에서 설정)


@dataclass(frozen=True)
class FacetDTO:
    id: str
    code: str
    name: str
    ord: int
    active: bool


@dataclass(frozen=True)
class OptionDTO:
    id: str
    code: str
    name: str
    ord: int
    active: bool
    default_unit: str
    geom_hint: str


# ─────────────────────────────────────────────────────────────────────────────
# 5) L1/L2 계산 로직 (※ level 컬럼 없이 처리)

def _get_l1_ids() -> List[str]:
    """
    L1 = 어떤 노드의 child_id로도 등장하지 않는 '루트 노드' 집합.
    (CategoryParent를 기준으로 계산)
    """
    child_ids = CategoryParent.objects.using(CENTRAL_ALIAS)\
        .values_list("child_id", flat=True)
    qs = CategoryNode.objects.using(CENTRAL_ALIAS)\
        .exclude(id__in=child_ids)\
        .order_by("ord", "name")
    return [str(n.id) for n in qs]


def _get_l2_ids() -> List[str]:
    """
    L2 = CategoryParent에 child로 등장하는 모든 노드.
    (단계가 더 있어도, 현재는 'L1 자식'을 L2로 쓴다는 전제)
    """
    child_ids = CategoryParent.objects.using(CENTRAL_ALIAS)\
        .values_list("child_id", flat=True)\
        .distinct()
    return [str(cid) for cid in child_ids]


def fetch_l1_list(only_active: bool = True) -> List[NodeDTO]:
    """
    중앙 카탈로그 L1 목록(루트 노드)
    """
    child_ids = CategoryParent.objects.using(CENTRAL_ALIAS)\
        .values_list("child_id", flat=True)
    qs = CategoryNode.objects.using(CENTRAL_ALIAS)\
        .exclude(id__in=child_ids)
    if only_active:
        qs = qs.filter(active=True)
    qs = qs.order_by("ord", "name")

    out: List[NodeDTO] = []
    for n in qs:
        out.append(
            NodeDTO(
                id=str(n.id),
                code=n.code,
                name=n.name,
                ord=n.ord,
                active=n.active,
                level=1,
            )
        )
    return out


def fetch_l2_list_for_l1(l1_id: str, only_active: bool = True) -> List[NodeDTO]:
    """
    중앙 카탈로그에서 특정 L1에 연결된 L2 목록
    - CategoryParent.parent_id = l1_id, child → L2 node
    """
    child_ids = CategoryParent.objects.using(CENTRAL_ALIAS)\
        .filter(parent_id=l1_id)\
        .values_list("child_id", flat=True)

    qs = CategoryNode.objects.using(CENTRAL_ALIAS)\
        .filter(id__in=child_ids)
    if only_active:
        qs = qs.filter(active=True)
    qs = qs.order_by("ord", "name")

    out: List[NodeDTO] = []
    for n in qs:
        out.append(
            NodeDTO(
                id=str(n.id),
                code=n.code,
                name=n.name,
                ord=n.ord,
                active=n.active,
                level=2,
            )
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 6) 테넌트 선택 L1/L2 조회 (멀티 체크)

def get_enabled_node_ids(
    tenant_alias: str,
    level: int,
    project_id: Optional[str] = None,
) -> Set[str]:
    """
    테넌트 DB에서 level(1 or 2)의 '선택된' 노드 id 집합을 돌려준다.
    - 중앙 CategoryNode에는 level 컬럼이 없으므로,
      level=1 → L1 후보(id 집합), level=2 → L2 후보(id 집합)와 교집합으로 제한.
    """
    try:
        # 실제 경로에 맞게 수정해서 사용:
        from geoflow_ops.tenant_models import TenantL1L2Selection
    except Exception:
        # 아직 테이블/모델이 없으면 빈 집합
        return set()

    if level == 1:
        candidate_ids = set(_get_l1_ids())
    elif level == 2:
        candidate_ids = set(_get_l2_ids())
    else:
        return set()

    qs = TenantL1L2Selection.objects.using(tenant_alias).filter(selected=True)
    if project_id:
        qs = qs.filter(project_id=project_id)

    picked: Set[str] = set()
    for sid in qs.values_list("node_id", flat=True):
        sid = str(sid)
        if sid in candidate_ids:
            picked.add(sid)
    return picked


# ─────────────────────────────────────────────────────────────────────────────
# 7) Lv2 → 옵션팩(=CategoryOptionSet) 가져오기

def get_option_sets_for_l2(l2_id: str) -> Dict[int, FacetDTO]:
    """
    결과 예: {3: FacetDTO(...), 4: FacetDTO(...)}
    (설계상 Lv2당 Lv3/Lv4 각각 1개씩 연결되어 있다고 가정)
    """
    sets = (
        CategoryOptionSet.objects.using(CENTRAL_ALIAS)
        .filter(l2_id=l2_id)
        .select_related("facet")
        .order_by("level_no", "ord")
    )
    out: Dict[int, FacetDTO] = {}
    for s in sets:
        f: CategoryFacet = s.facet
        out[int(s.level_no)] = FacetDTO(
            id=str(f.id),
            code=f.code,
            name=f.name,
            ord=f.ord,
            active=f.active,
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 8) Lv3/Lv4 옵션 목록(중앙) - (Pick 테이블이 없다고 가정, 팩의 전체 옵션 사용)

def get_all_options_of_facet(facet_id: str, only_active: bool = True) -> List[OptionDTO]:
    qs = CategoryFacetOption.objects.using(CENTRAL_ALIAS).filter(facet_id=facet_id)
    if only_active:
        qs = qs.filter(active=True)
    qs = qs.order_by("ord", "name")

    out: List[OptionDTO] = []
    for o in qs:
        out.append(
            OptionDTO(
                id=str(o.id),
                code=o.code,
                name=o.name,
                ord=o.ord,
                active=o.active,
                default_unit=getattr(o, "default_unit", ""),  # 필드 없으면 빈 문자열
                geom_hint=getattr(o, "geom_hint", ""),        # 필드 없으면 빈 문자열
            )
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 9) 테넌트 비활성 옵션(OFF 스위치) 조회

def get_disabled_option_ids(
    tenant_alias: str,
    l2_id: str,
    level_no: int,
    project_id: Optional[str] = None,
) -> Set[str]:
    try:
        # 실제 경로로 변경 필요
        from geoflow_ops.tenant_models import TenantOptionDisable
    except Exception:
        return set()

    qs = TenantOptionDisable.objects.using(tenant_alias).filter(
        l2_id=l2_id,
        level_no=level_no,
    )
    if project_id:
        qs = qs.filter(project_id=project_id)
    return set(str(x) for x in qs.values_list("option_id", flat=True))


# ─────────────────────────────────────────────────────────────────────────────
# 10) 최종(Effective) 옵션 목록 = (중앙 전체 옵션) - (테넌트 비활성)

def get_effective_options(
    tenant_alias: str,
    l2_id: str,
    level_no: int,
    project_id: Optional[str] = None,
    only_active: bool = True,
) -> List[OptionDTO]:
    """
    1) CategoryOptionPick 으로 L2 + level_no 에 대해 pick된 옵션만 가져온다.
    2) 테넌트 비활성 목록을 빼준다.
    """
    # 1) 중앙 pick 기준 옵션 목록
    all_opts = get_picked_options_for_l2(l2_id, int(level_no), only_active=only_active)

    # 2) 테넌트 비활성 (OFF 스위치)
    disabled = get_disabled_option_ids(tenant_alias, l2_id, int(level_no), project_id)

    # 3) 비활성 목록을 제외한 최종 옵션
    return [o for o in all_opts if o.id not in disabled]


# ─────────────────────────────────────────────────────────────────────────────
# 11) 규칙(선택) - 중앙 룰만 사용(오버라이드 없음 가정)

def get_rules_pairs(l2_id: str, only_active: bool = True) -> Set[Tuple[str, str]]:
    """
    규칙은 (facet3_opt_id, facet4_opt_id) 페어 집합으로 반환.
    """
    qs = CategoryOptionRule.objects.using(CENTRAL_ALIAS).filter(l2_id=l2_id)
    if hasattr(CategoryOptionRule, "active") and only_active:
        qs = qs.filter(active=True)
    return set((str(r.facet3_opt_id), str(r.facet4_opt_id)) for r in qs)


# ─────────────────────────────────────────────────────────────────────────────
# 12) 보드/화면용 합성 유틸 (한 번에 가져오기)

def build_l2_panel_data(
    tenant_alias: str,
    l1_id: str,
    project_id: Optional[str] = None,
    only_active: bool = True,
) -> Dict[str, object]:
    """
    - L2 리스트(중앙) + 테넌트 선택 여부
    - 각 L2별 Lv3/Lv4 옵션팩, Effective 옵션 목록(비활성 제외)
    """
    l2_list = fetch_l2_list_for_l1(l1_id, only_active=only_active)
    enabled_l2_ids = get_enabled_node_ids(tenant_alias, level=2, project_id=project_id)

    out = {
        "l2": [],  # [{node, selected, sets:{3:facetDTO,4:facetDTO}, options:{3:[...],4:[...]}}...]
    }
    for n in l2_list:
        sets = get_option_sets_for_l2(n.id)
        opts3 = get_effective_options(
            tenant_alias,
            n.id,
            level_no=3,
            project_id=project_id,
            only_active=only_active,
        )
        opts4 = get_effective_options(
            tenant_alias,
            n.id,
            level_no=4,
            project_id=project_id,
            only_active=only_active,
        )
        out["l2"].append(
            {
                "node": n,
                "selected": (n.id in enabled_l2_ids),
                "sets": {k: v for k, v in sets.items()},
                "options": {
                    3: opts3,
                    4: opts4,
                },
            }
        )
    return out


# ─────────────────────────────────────────────────────────────────────────────
# 13) 픽된 옵션들 가져오기

def get_picked_options_for_l2(
    l2_id: str,
    level_no: int,
    only_active: bool = True,
) -> List[OptionDTO]:
    """
    catalog.category_option_pick 을 기준으로
    - 특정 L2 + level_no(3 or 4)에 대해
    - 중앙에서 '선택(pick)'된 옵션만 반환.
    """
    picks = (
        CategoryOptionPick.objects
        .using(CENTRAL_ALIAS)
        .filter(l2_id=l2_id, level_no=level_no)
        .select_related("option")
        .order_by("ord", "option__ord", "option__name")
    )

    out: List[OptionDTO] = []
    for p in picks:
        opt = p.option  # 🔹 CategoryOptionPick.option 이 FK 여야 함
        if only_active and not opt.active:
            continue
        out.append(
            OptionDTO(
                id=str(opt.id),
                code=opt.code,
                name=opt.name,
                ord=opt.ord,
                active=opt.active,
                default_unit=opt.default_unit,
                geom_hint=opt.geom_hint,
            )
        )
    return out