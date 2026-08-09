from __future__ import annotations

from uuid import uuid4

from django.contrib import messages
from django.db import connections, transaction
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_protect

from .decorators import require_central_admin


@require_central_admin
@csrf_protect
def users_assign_group_admin(request, user_id):
    """Assign one active tenant/group role without relying on an ON CONFLICT index.

    The central tables predate Django ownership and may not have the model-declared
    ``(user_id, group_id)`` unique constraint in every deployed schema generation.
    Locking the eligible user/group/role and performing update-then-insert keeps the
    operation idempotent without requiring a production migration as part of this
    hotfix.
    """

    if request.method != "POST":
        return redirect("control:users_detail_admin", user_id=user_id)

    group_id = request.POST.get("group_id")
    role_id = request.POST.get("role_id")
    if not group_id or not role_id:
        messages.error(request, "그룹과 역할을 선택하세요.")
        return redirect("control:users_detail_admin", user_id=user_id)

    assigned = False
    with transaction.atomic(using="default"):
        with connections["default"].cursor() as cur:
            cur.execute(
                """
                SELECT u.id::text, g.id::text, r.id::text
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
                 FOR UPDATE OF u, g, r
                """,
                [group_id, role_id, str(user_id)],
            )
            eligible = cur.fetchone()

            if eligible:
                eligible_user_id, eligible_group_id, eligible_role_id = eligible
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
                    [eligible_role_id, eligible_user_id, eligible_group_id],
                )
                assigned = cur.fetchone() is not None

                if not assigned:
                    cur.execute(
                        """
                        INSERT INTO user_group_map(
                            id, user_id, group_id, role_id,
                            status, created_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, 'active', now(), now())
                        RETURNING id
                        """,
                        [
                            str(uuid4()),
                            eligible_user_id,
                            eligible_group_id,
                            eligible_role_id,
                        ],
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
