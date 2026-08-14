# control/views_groups.py
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import HttpResponseForbidden
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_GET, require_POST

from control.services import central_repo as C
from control.services.tenant_selection import refresh_server_issued_tenant_candidates
from control.services_identity import lookup_user_id_from_request


def _refresh_session_candidates(request, user_id):
    candidates = refresh_server_issued_tenant_candidates(
        user_id,
        request.session.get("tenant_candidates", []),
    )
    if candidates:
        request.session["tenant_candidates"] = candidates
    else:
        request.session.pop("tenant_candidates", None)
    return candidates


@login_required
@require_GET
def group_search_view(request):
    uid = lookup_user_id_from_request(request)
    if not uid:
        return redirect("login")

    candidates = _refresh_session_candidates(request, uid)
    if not candidates:
        return redirect("after_login")

    q = (request.GET.get("q") or "").strip()
    q_lower = q.lower()
    rows = [
        (item["id"], item.get("code", ""), item.get("name", ""), "active")
        for item in candidates
        if not q_lower
        or q_lower in (item.get("code") or "").lower()
        or q_lower in (item.get("name") or "").lower()
    ]
    return render(request, "control/group_search.html", {"rows": rows, "q": q})


@login_required
@require_POST
@csrf_protect
def group_select_view(request, group_id):
    """Select one live, server-issued tenant candidate through a CSRF-protected POST."""

    uid = lookup_user_id_from_request(request)
    if not uid:
        messages.error(request, "로그인 후 이용하세요.")
        return redirect("/login/")

    candidates = _refresh_session_candidates(request, uid)
    selected_id = str(group_id)
    candidate = next(
        (
            item
            for item in candidates
            if str(item.get("id")) == selected_id
        ),
        None,
    )
    if not candidate:
        return HttpResponseForbidden("Forbidden")

    request.session["group_uuid"] = candidate["id"]
    request.session["group_id"] = candidate["id"]
    request.session["tenant_db_alias"] = candidate["db_alias"]
    request.session["db_key"] = candidate["db_alias"]

    try:
        roles = C.list_roles_for_user_in_group(uid, candidate["id"])
    except Exception:
        roles = []
    request.session["roles"] = roles
    request.session.pop("tenant_candidates", None)

    return redirect("after_login")
