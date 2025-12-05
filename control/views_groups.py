# control/views_groups.py
from django.shortcuts import render, redirect
from django.db import connections
from django.contrib import messages
from control.services_identity import ensure_user_from_request

def group_search_view(request):
    q = (request.GET.get("q") or "").strip()
    rows = []
    with connections["default"].cursor() as cur:
        if q:
            cur.execute("""
                SELECT id::text, code, name, status
                  FROM groups
                 WHERE status='active'
                   AND (code ILIKE %s OR name ILIKE %s)
                 ORDER BY name
                 LIMIT 200
            """, [f"%{q}%", f"%{q}%"])
        else:
            cur.execute("""
                SELECT id::text, code, name, status
                  FROM groups
                 WHERE status='active'
                 ORDER BY created_at DESC
                 LIMIT 50
            """)
        rows = cur.fetchall()
    return render(request, "control/group_search.html", {"rows": rows, "q": q})

def group_select_view(request, group_id):
    """
    단순히 세션 group_id만 세팅하고 /after-login 으로 넘김.
    실제 멤버십/권한은 이후 데코레이터와 템플릿태그에서 서버‑사이드로 검증됨.
    """
    uid = ensure_user_from_request(request)
    if not uid:
        messages.error(request, "로그인 후 이용하세요.")
        return redirect("/login/")

    request.session["group_id"] = str(group_id)
    return redirect("post_login_redirect")
