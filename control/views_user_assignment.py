from __future__ import annotations

from uuid import uuid4

from django.contrib import messages
from django.db import connections, transaction
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST

from .decorators import require_central_admin
from .services_identity import lookup_user_id_from_request


def _column_exists(cur, table: str, column: str) -> bool:
    cur.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_schema=current_schema()
           AND table_name=%s
           AND column_name=%s
         LIMIT 1
        """,
        [table, column],
    )
    return cur.fetchone() is not None


@require_central_admin
@csrf_protect
def users_assign_group_admin(request, user_id):
    """Assign one active tenant/group role without requiring a membership unique index.

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

    assigned = assign_group_role(user_id, group_id, role_id)

    if not assigned:
        messages.error(
            request,
            "활성화된 사용자와 유효한 그룹/역할만 지정할 수 있습니다.",
        )
        return redirect("control:users_detail_admin", user_id=user_id)

    messages.success(request, "그룹/역할이 지정되었습니다.")
    return redirect("control:users_detail_admin", user_id=user_id)


def assign_group_role(user_id, group_id, role_id, *, before_assign=None):
    """Shared locked eligibility and membership write for explicit admin actions.

    before_assign runs under the central locks, before any membership mutation.
    A failure rolls back this central transaction; external commits are journaled
    by the caller and can be reconciled through an idempotent retry.
    """
    assigned = False
    with transaction.atomic(using="default"):
        with connections["default"].cursor() as cur:
            role_status_clause = ""
            if _column_exists(cur, "roles", "status"):
                role_status_clause = (
                    "AND lower(COALESCE(r.status, ''))='active'"
                )

            cur.execute(
                f"""
                SELECT u.id::text, g.id::text, r.id::text
                  FROM users u
                  JOIN groups g
                    ON g.id=%s
                   AND lower(COALESCE(g.status, ''))='active'
                  JOIN roles r
                    ON r.id=%s
                   {role_status_clause}
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
                if before_assign is not None:
                    before_assign(cur, eligible)
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
                if before_assign is not None and not assigned:
                    raise RuntimeError("Membership write was not confirmed")

    return assigned


@transaction.non_atomic_requests(using="default")
@require_central_admin
@csrf_protect
@require_POST
def users_register_employee_admin(request, user_id):
    from .services.tenant_employee_registration import (
        RegistrationRejected, register_tenant_employee,
    )

    try:
        register_tenant_employee(
            user_id=user_id,
            group_id=request.POST.get("group_id"),
            role_id=request.POST.get("role_id"),
            actor_user_id=lookup_user_id_from_request(request),
            name=request.POST.get("employee_name", ""),
        )
    except RegistrationRejected as exc:
        messages.error(request, str(exc))
    except (ValueError, TypeError):
        messages.error(request, "계정·테넌트·역할을 확인하세요.")
    except Exception:
        messages.error(request, "직원 등록을 시작하지 못했습니다. 중앙 등록 기능의 준비 상태를 확인하세요.")
    else:
        messages.success(request, "테넌트 직원 등록과 역할 부여가 완료되었습니다. 기존 직원 정보는 유지됩니다.")
    return redirect("control:users_detail_admin", user_id=user_id)
