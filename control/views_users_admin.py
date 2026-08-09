# control/views_users_admin.py
from types import SimpleNamespace
from uuid import uuid4

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.hashers import make_password
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError
from django.db import connections, transaction
from django.shortcuts import redirect, render
from django.utils import timezone
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from .decorators import require_central_admin
from .services.central_account_erasure_service import (
    AccountErasureError,
    erase_central_account_personal_data,
)
from .services.legacy_password_setup_compatibility import (
    LegacyPasswordSetupSignupConflict,
    require_legacy_password_setup_compatible,
)
from .services_identity import lookup_user_id_from_request


MAX_LEGACY_PASSWORD_LENGTH = 128


def _column_exists(cursor, table: str, column: str) -> bool:
    cursor.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema='public'
           AND table_name=%s
           AND column_name=%s
         LIMIT 1
        """,
        [table, column],
    )
    return cursor.fetchone() is not None


def _join_request_rows(cursor, *, user_id: str, email: str):
    """Read legacy or current join-request shapes without assuming one email/role column."""

    email_columns = [
        column
        for column in ("requested_email", "email")
        if _column_exists(cursor, "join_requests", column)
    ]
    if _column_exists(cursor, "join_requests", "requested_role_code"):
        role_expression = "jr.requested_role_code"
        role_join = ""
    elif _column_exists(cursor, "join_requests", "role_id"):
        role_expression = "r.code"
        role_join = "JOIN roles r ON r.id=jr.role_id"
    else:
        role_expression = "NULL::text"
        role_join = ""

    filters = ["COALESCE(jr.user_id::text,'')=%s"]
    params = [user_id]
    for column in email_columns:
        filters.append(f"lower({column})=lower(%s)")
        params.append(email)

    cursor.execute(
        f"""
        SELECT jr.id::text, g.name, g.code, {role_expression},
               jr.status, jr.created_at
          FROM join_requests jr
          JOIN groups g ON g.id=jr.group_id
          {role_join}
         WHERE {' OR '.join(filters)}
         ORDER BY jr.created_at DESC
        """,
        params,
    )
    return cursor.fetchall()


@sensitive_post_parameters("password", "password2")
@sensitive_variables("email", "pw1", "pw2", "hashed")
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def set_password_view(request, token):
    with connections["default"].cursor() as cur:
        cur.execute(
            """
          SELECT prt.user_id::text, u.email, prt.expires_at, prt.used
            FROM password_reset_tokens prt
            JOIN users u ON u.id = prt.user_id
           WHERE prt.token=%s
        """,
            [str(token)],
        )
        row = cur.fetchone()
    if not row:
        return render(request, "control/set_password.html", {"invalid": True})

    user_id, email, expires_at, used = row
    if used or expires_at < timezone.now():
        return render(
            request,
            "control/set_password.html",
            {"expired": True, "email": email},
        )

    try:
        require_legacy_password_setup_compatible(user_id)
    except LegacyPasswordSetupSignupConflict:
        return render(request, "control/set_password.html", {"invalid": True})

    if request.method == "GET":
        return render(request, "control/set_password.html", {"email": email})

    pw1 = request.POST.get("password") or ""
    pw2 = request.POST.get("password2") or ""
    password_invalid = (
        not pw1
        or pw1 != pw2
        or len(pw1) > MAX_LEGACY_PASSWORD_LENGTH
    )
    if not password_invalid:
        validator_user = SimpleNamespace(
            username=email,
            email=email,
            first_name="",
            last_name="",
        )
        try:
            validate_password(pw1, user=validator_user)
        except ValidationError:
            password_invalid = True

    if password_invalid:
        messages.error(
            request,
            "비밀번호가 조건에 맞지 않거나 일치하지 않습니다.",
        )
        return render(request, "control/set_password.html", {"email": email})

    hashed = make_password(pw1)
    token_invalidated = False
    with transaction.atomic():
        with connections["default"].cursor() as cur:
            cur.execute(
                """
              SELECT prt.user_id::text, u.email, prt.expires_at, prt.used
                FROM password_reset_tokens prt
                JOIN users u ON u.id = prt.user_id
               WHERE prt.token=%s
               FOR UPDATE OF prt
            """,
                [str(token)],
            )
            locked_row = cur.fetchone()
            if (
                not locked_row
                or str(locked_row[0]) != str(user_id)
                or locked_row[3]
                or locked_row[2] < timezone.now()
            ):
                token_invalidated = True
            else:
                cur.execute(
                    """
                  UPDATE users SET password_hash=%s, email_verified=TRUE, updated_at=now()
                   WHERE id=%s
                """,
                    [hashed, user_id],
                )
                cur.execute(
                    """
                  UPDATE password_reset_tokens
                     SET used=TRUE
                   WHERE token=%s AND used=FALSE
                """,
                    [str(token)],
                )

    if token_invalidated:
        return render(request, "control/set_password.html", {"invalid": True})

    messages.success(
        request,
        "비밀번호가 설정되었습니다. 계정이 승인되어 활성 상태인 경우 로그인할 수 "
        "있습니다. 승인대기 계정은 관리자 승인 후 로그인할 수 있습니다.",
    )
    return redirect("login")


@require_central_admin
def users_list_admin(request):
    with connections["default"].cursor() as cur:
        cur.execute(
            """
          SELECT u.id::text, u.email, u.is_active, u.email_verified, u.last_login,
                 (SELECT COUNT(*) FROM user_group_map ugm WHERE ugm.user_id=u.id) AS groups_count
            FROM users u
           ORDER BY u.created_at DESC
           LIMIT 500
        """
        )
        rows = cur.fetchall()
    users = [
        {
            "id": r[0],
            "email": r[1],
            "is_active": r[2],
            "email_verified": r[3],
            "last_login": r[4],
            "groups_count": r[5],
        }
        for r in rows
    ]
    return render(request, "control/users_list_admin.html", {"users": users})


@require_central_admin
def users_detail_admin(request, user_id):
    with connections["default"].cursor() as cur:
        cur.execute(
            """
          SELECT u.id::text, u.email, u.is_active, u.email_verified, u.last_login, u.created_at, u.updated_at
            FROM users u
           WHERE u.id=%s
        """,
            [str(user_id)],
        )
        u = cur.fetchone()
        if not u:
            messages.error(request, "사용자를 찾을 수 없습니다.")
            return redirect("control:users_list_admin")
        cur.execute(
            """
          SELECT g.id::text, g.name, g.code, r.id::text, r.code, r.name, ugm.status
            FROM user_group_map ugm
            JOIN groups g ON g.id=ugm.group_id
            JOIN roles  r ON r.id=ugm.role_id
           WHERE ugm.user_id=%s
        """,
            [str(user_id)],
        )
        memberships = cur.fetchall()

        requests = _join_request_rows(
            cur,
            user_id=str(user_id),
            email=str(u[1]),
        )

        cur.execute(
            """
          SELECT g.id::text, g.name, g.code
            FROM groups g
           WHERE lower(COALESCE(g.status, ''))='active'
           ORDER BY g.name
        """
        )
        groups = cur.fetchall()

        cur.execute(
            """
          SELECT r.id::text, r.code
            FROM roles r
           ORDER BY r.code
        """
        )
        roles = cur.fetchall()

    membership_rows = [
        {
            "group_id": m[0],
            "group_name": m[1],
            "group_code": m[2],
            "role_id": m[3],
            "role_code": m[4],
            "role_name": m[5],
            "status": m[6],
        }
        for m in memberships
    ]
    selected_membership = next(
        (
            membership
            for membership in membership_rows
            if (membership.get("status") or "").lower() == "active"
        ),
        membership_rows[0] if membership_rows else None,
    )
    request_rows = [
        {
            "id": r[0],
            "group_name": r[1],
            "group_code": r[2],
            "role_code": r[3],
            "status": r[4],
            "created_at": r[5],
        }
        for r in requests
    ]

    ctx = {
        "user": {
            "id": u[0],
            "email": u[1],
            "is_active": u[2],
            "email_verified": u[3],
            "last_login": u[4],
            "created_at": u[5],
            "updated_at": u[6],
        },
        "memberships": membership_rows,
        "requests": request_rows,
        "joins": request_rows,
        "groups": [
            {"id": g[0], "name": g[1], "code": g[2]} for g in groups
        ],
        "roles": [{"id": r[0], "code": r[1]} for r in roles],
        "selected_group_id": (
            selected_membership["group_id"] if selected_membership else None
        ),
        "selected_role_id": (
            selected_membership["role_id"] if selected_membership else None
        ),
        "membership_role_by_group": {
            membership["group_id"]: membership["role_id"]
            for membership in membership_rows
        },
    }
    return render(request, "control/users_detail_admin.html", ctx)


@require_central_admin
@csrf_protect
def users_delete_admin(request, user_id):
    if request.method != "POST":
        messages.error(request, "잘못된 접근입니다.")
        return redirect("control:users_detail_admin", user_id=user_id)

    actor_user_id = lookup_user_id_from_request(request)
    if actor_user_id is not None and str(actor_user_id) == str(user_id):
        messages.error(
            request,
            "현재 로그인한 중앙 관리자 계정은 이 화면에서 직접 삭제할 수 없습니다.",
        )
        return redirect("control:users_detail_admin", user_id=user_id)

    try:
        result = erase_central_account_personal_data(str(user_id))
    except (AccountErasureError, ValueError):
        messages.error(
            request,
            "사용자 개인정보 삭제를 완료할 수 없습니다. 연관 데이터 상태를 확인하세요.",
        )
        return redirect("control:users_detail_admin", user_id=user_id)

    if result.mode == "anonymized":
        messages.success(
            request,
            "사용자 계정 개인정보가 삭제되고 감사 이력용 식별자는 익명화되었습니다.",
        )
    else:
        messages.success(request, "사용자 계정 개인정보가 삭제되었습니다.")
    return redirect("control:users_list_admin")


@require_central_admin
@csrf_protect
def users_assign_group_admin(request, user_id):
    if request.method != "POST":
        return redirect("control:users_detail_admin", user_id=user_id)
    group_id = request.POST.get("group_id")
    role_id = request.POST.get("role_id")
    if not group_id or not role_id:
        messages.error(request, "그룹과 역할을 선택하세요.")
        return redirect("control:users_detail_admin", user_id=user_id)

    assigned = False
    with transaction.atomic():
        with connections["default"].cursor() as cur:
            # Lock the user row so concurrent manual assignments for the same
            # account serialize without depending on a physical legacy-schema
            # unique constraint.
            cur.execute(
                """
                SELECT u.id::text
                  FROM users u
                  JOIN groups g
                    ON g.id=%s
                   AND lower(COALESCE(g.status, ''))='active'
                  JOIN roles r ON r.id=%s
                 WHERE u.id=%s
                   AND u.is_active=TRUE
                   AND u.email_verified=TRUE
                   AND u.password_hash IS NOT NULL
                   AND length(trim(u.password_hash)) > 0
                   AND (
                       u.password_hash LIKE 'pbkdf2_sha256$%%'
                       OR u.password_hash LIKE 'bcrypt_sha256$%%'
                       OR u.password_hash LIKE '$2a$%%'
                       OR u.password_hash LIKE '$2b$%%'
                       OR u.password_hash LIKE '$2y$%%'
                   )
                 FOR UPDATE OF u
                """,
                [group_id, role_id, str(user_id)],
            )
            eligible = cur.fetchone() is not None

            if eligible:
                cur.execute(
                    """
                    UPDATE user_group_map
                       SET role_id=%s,
                           status='active',
                           updated_at=now()
                     WHERE user_id=%s
                       AND group_id=%s
                     RETURNING id
                    """,
                    [role_id, str(user_id), group_id],
                )
                assigned = cur.fetchone() is not None

                if not assigned:
                    cur.execute(
                        """
                        INSERT INTO user_group_map(
                            id, user_id, group_id, role_id, status, created_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, 'active', now(), now())
                        RETURNING id
                        """,
                        [str(uuid4()), str(user_id), group_id, role_id],
                    )
                    assigned = cur.fetchone() is not None

    if not assigned:
        messages.error(
            request,
            "활성화된 사용자와 유효한 그룹/역할만 지정할 수 있습니다.",
        )
        return redirect("control:users_detail_admin", user_id=user_id)

    messages.success(request, "그룹/역할이 지정되었습니다.")
    return redirect("control:users_detail_admin", user_id=user_id)


@login_required
def dashboard(request):
    return render(request, "control/dashboard.html", {})
