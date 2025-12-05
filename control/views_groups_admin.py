from django.conf import settings
from django.shortcuts import render, redirect
from django.contrib import messages
from django.db import connections
from django.views.decorators.csrf import csrf_protect
from django.contrib.auth.decorators import login_required

from control.decorators import require_central_admin
from control.services import central_repo as C


STATUS_CHOICES = ["active", "inactive"]
CENTRAL = getattr(settings, "CENTRAL_DB_ALIAS", "default")

def _central_alias():
    return CENTRAL

def _resolve_tenant_alias_by_group(group_id: str) -> str:
    # 중앙DB에서 그룹 코드(or db_alias 컬럼)를 읽어서 DB 별칭 산출
    with connections[CENTRAL].cursor() as cur:
        cur.execute("SELECT code FROM groups WHERE id=%s", [str(group_id)])
        row = cur.fetchone()
    if not row:
        return "default"
    code = row[0]
    # 네 환경에 맞춰 매핑 규칙/컬럼 사용. (예: code + '_db' 또는 groups.db_alias 컬럼)
    candidate = f"{code}_db"
    return candidate if candidate in settings.DATABASES else "default"

def group_select(request, group_id):
    # 중앙에서 그룹코드 → DB 별칭 매핑
    with connections[_central_alias()].cursor() as cur:
        cur.execute("SELECT code FROM groups WHERE id=%s", [str(group_id)])
        row = cur.fetchone()
    alias = f"{row[0]}_db" if row and f"{row[0]}_db" in settings.DATABASES else getattr(settings, "DEFAULT_TENANT_DB_ALIAS", "default")

    request.session['group_uuid'] = str(group_id)
    request.session['tenant_db_alias'] = alias
    return redirect("home")

@require_central_admin
def group_list_admin(request):
    rows = C.list_groups_admin()  # (id, code, name, status, domains, owner_email, db_alias) 7튜플
    return render(request, "control/group_list_admin.html", {"rows": rows})


@require_central_admin
@csrf_protect
def group_create_admin(request):
    if request.method == "POST":
        code = (request.POST.get("code") or "").strip().lower()
        name = (request.POST.get("name") or "").strip()
        domains = (request.POST.get("allowed_domains") or "").strip()
        owner = (request.POST.get("owner_email") or "").strip().lower()
        db_alias = (request.POST.get("db_alias") or "").strip()

        if not code or not name:
            messages.error(request, "코드/이름은 필수입니다.")
            return render(request, "control/group_form_admin.html")

        allowed = [d.strip().lower() for d in domains.replace(";", ",").split(",") if d.strip()]

        with connections[_central_alias()].cursor() as cur:
            cur.execute("SELECT 1 FROM groups WHERE code=%s", [code])
            if cur.fetchone():
                messages.error(request, "이미 존재하는 코드입니다.")
                return render(request, "control/group_form_admin.html")

            owner_id = None
            if owner:
                cur.execute("SELECT id FROM users WHERE email=%s", [owner])
                row = cur.fetchone()
                if row: owner_id = row[0]

            cur.execute("""
                INSERT INTO groups(id, code, name, status, allowed_domains, owner_user_id, created_at, updated_at)
                VALUES (gen_random_uuid(), %s, %s, 'active', %s, %s, now(), now())
            """, [code, name, allowed or None, owner_id])

        messages.success(request, "그룹이 생성되었습니다.")
        return redirect("group_list_admin")

    return render(request, "control/group_form_admin.html", {
        "row": None,
        "status_choices": STATUS_CHOICES,
    })


@require_central_admin
@csrf_protect
def group_edit_admin(request, group_id):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        status = (request.POST.get("status") or "active").strip()
        domains = (request.POST.get("allowed_domains") or "").strip()
        owner = (request.POST.get("owner_email") or "").strip().lower()

        allowed = [d.strip().lower() for d in domains.replace(";", ",").split(",") if d.strip()]

        with connections[_central_alias()].cursor() as cur:
            owner_id = None
            if owner:
                cur.execute("SELECT id FROM users WHERE email=%s", [owner])
                row = cur.fetchone()
                if row: owner_id = row[0]

            cur.execute("""
                UPDATE groups
                   SET name = COALESCE(%s, name),
                       status = %s,
                       allowed_domains = %s,
                       owner_user_id = %s,
                       updated_at = now()
                 WHERE id=%s
            """, [name or None, status, allowed or None, owner_id, group_id])

        messages.success(request, "수정되었습니다.")
        return redirect("group_list_admin")

    with connections[_central_alias()].cursor() as cur:
        cur.execute("""
            SELECT g.id::text, g.code, g.name, g.status,
                   ARRAY_TO_STRING(g.allowed_domains, ',') AS domains,
                   u.email AS owner_email
              FROM groups g
              LEFT JOIN users u ON u.id = g.owner_user_id
             WHERE g.id=%s
             LIMIT 1
        """, [group_id])
        row = cur.fetchone()

    return render(request, "control/group_form_admin.html", {
        "row": row,
        "status_choices": STATUS_CHOICES,
    })