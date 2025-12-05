# control/views_categories.py
from django.shortcuts import render
from django.http import JsonResponse, HttpResponseBadRequest
from django.views.decorators.http import require_GET
from django.db import connections

# ⬇️ 프로젝트 내 실제 위치에 맞춰 import 경로 조정하세요.
#    지시사항: _alias = current_db_alias() 그대로 사용
# from geoflow_ops.db import current_db_alias  # <- 실제 경로로 변경 필요
from control.middleware import current_db_alias

def _alias(request):
    return current_db_alias()

def categories_page(request):
    """
    중앙 > 카테고리: L1 드롭다운, 선택 시 L2 자동 로드
    """
    alias = _alias(request)
    return render(request, "control/categories.html", {"db_alias": alias})

@require_GET
def category_options(request):
    """
    AJAX:
      - level=1: L1 전체
      - level=2 & parent_id: 해당 L1의 직속 L2
    """
    try:
        level = int(request.GET.get("level", "1"))
    except ValueError:
        return HttpResponseBadRequest("level must be int")

    alias = _alias(request)

    if level == 1:
        sql = """
            SELECT id::text, code, name, ord
            FROM cat.prj_category
            WHERE active = TRUE AND level = 1
            ORDER BY ord NULLS LAST, name
        """
        with connections[alias].cursor() as cur:
            cur.execute(sql)
            rows = cur.fetchall()
        data = [{"id": r[0], "code": r[1], "name": r[2], "ord": r[3]} for r in rows]
        return JsonResponse({"results": data})

    if level == 2:
        parent_id = request.GET.get("parent_id")
        if not parent_id:
            return HttpResponseBadRequest("parent_id is required for level=2")

        sql = """
            SELECT c.id::text, c.code, c.name, c.ord
            FROM cat.prj_category_edge e
            JOIN cat.prj_category p ON p.id = e.parent_id
            JOIN cat.prj_category c ON c.id = e.child_id
            WHERE p.id = %s
              AND c.active = TRUE
              AND c.level = 2
            ORDER BY c.ord NULLS LAST, c.name
        """
        with connections[alias].cursor() as cur:
            cur.execute(sql, [parent_id])
            rows = cur.fetchall()
        data = [{"id": r[0], "code": r[1], "name": r[2], "ord": r[3]} for r in rows]
        return JsonResponse({"results": data})

    return HttpResponseBadRequest("unsupported level")
