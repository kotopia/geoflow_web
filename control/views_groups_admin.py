from django.conf import settings
from django.contrib import messages
from django.db import connections
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_http_methods

from control.decorators import require_central_admin
from control.services import central_repo as C


STATUS_CHOICES = ["active", "inactive"]
CENTRAL = getattr(settings, "CENTRAL_DB_ALIAS", "default")


def _central_alias():
    return CENTRAL


@require_central_admin
def group_list_admin(request):
    rows = C.list_groups_admin()
    return render(request, "control/group_list_admin.html", {"rows": rows})


@require_central_admin
@csrf_protect
@require_http_methods(["GET", "POST"])
def group_create_admin(request):
    if request.method == "POST":
        code = (request.POST.get("code") or "").strip().lower()
        name = (request.POST.get("name") or "").strip()
        domains = (request.POST.get("allowed_domains") or "").strip()
        owner = (request.POST.get("owner_email") or "").strip().lower()
        if not code or not name:
            messages.error(request, "코드/이름은 필수입니다.")
            return render(request, "control/group_form_admin.html")

        allowed = [
            d.strip().lower()
            for d in domains.replace(";", ",").split(",")
            if d.strip()
        ]

        with connections[_central_alias()].cursor() as cur:
            cur.execute("SELECT 1 FROM groups WHERE code=%s", [code])
            if cur.fetchone():
                messages.error(request, "이미 존재하는 코드입니다.")
                return render(request, "control/group_form_admin.html")

            owner_id = None
            if owner:
                cur.execute(
                    "SELECT id FROM users WHERE lower(email)=lower(%s)",
                    [owner],
                )
                row = cur.fetchone()
                if row:
                    owner_id = row[0]

            cur.execute(
                """
                INSERT INTO groups(
                    id, code, name, status, allowed_domains,
                    owner_user_id, created_at, updated_at
                )
                VALUES (
                    gen_random_uuid(), %s, %s, 'active', %s, %s, now(), now()
                )
                """,
                [code, name, allowed or None, owner_id],
            )

        messages.success(request, "그룹이 생성되었습니다.")
        return redirect("control:group_list_admin")

    return render(
        request,
        "control/group_form_admin.html",
        {"row": None, "status_choices": STATUS_CHOICES},
    )


@require_central_admin
@csrf_protect
@require_http_methods(["GET", "POST"])
def group_edit_admin(request, group_id):
    if request.method == "POST":
        name = (request.POST.get("name") or "").strip()
        status = (request.POST.get("status") or "active").strip().lower()
        domains = (request.POST.get("allowed_domains") or "").strip()
        owner = (request.POST.get("owner_email") or "").strip().lower()

        if status not in STATUS_CHOICES:
            messages.error(request, "올바르지 않은 그룹 상태입니다.")
            return redirect("control:group_edit_admin", group_id=group_id)

        allowed = [
            d.strip().lower()
            for d in domains.replace(";", ",").split(",")
            if d.strip()
        ]

        with connections[_central_alias()].cursor() as cur:
            owner_id = None
            if owner:
                cur.execute(
                    "SELECT id FROM users WHERE lower(email)=lower(%s)",
                    [owner],
                )
                row = cur.fetchone()
                if row:
                    owner_id = row[0]

            cur.execute(
                """
                UPDATE groups
                   SET name = COALESCE(%s, name),
                       status = %s,
                       allowed_domains = %s,
                       owner_user_id = %s,
                       updated_at = now()
                 WHERE id=%s
                """,
                [name or None, status, allowed or None, owner_id, group_id],
            )

        messages.success(request, "수정되었습니다.")
        return redirect("control:group_list_admin")

    has_db_config = C._table_exists(_central_alias(), "group_db_config")
    db_alias_select = "c.db_alias" if has_db_config else "NULL::text"
    db_alias_join = (
        "LEFT JOIN group_db_config c ON c.group_id = g.id"
        if has_db_config
        else ""
    )

    with connections[_central_alias()].cursor() as cur:
        cur.execute(
            f"""
            SELECT g.id::text, g.code, g.name, g.status,
                   ARRAY_TO_STRING(g.allowed_domains, ',') AS domains,
                   u.email AS owner_email,
                   {db_alias_select} AS db_alias
              FROM groups g
              LEFT JOIN users u ON u.id = g.owner_user_id
              {db_alias_join}
             WHERE g.id=%s
             LIMIT 1
            """,
            [group_id],
        )
        row = cur.fetchone()

    return render(
        request,
        "control/group_form_admin.html",
        {"row": row, "status_choices": STATUS_CHOICES},
    )
