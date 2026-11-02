"""Explicit central-admin employee registration, with recoverable two-DB writes."""
from uuid import UUID, uuid4

from django.db import connections, transaction

from control.services.gis_admin import tenant_cursor
from control.services.tenant_role_request_service import (
    TenantRoleRequestRejected, _normalize_role_code,
)
from control.views_user_assignment import assign_group_role


class RegistrationRejected(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def register_employee_profile(cursor, *, user_id, email, name):
    # Serialize against ALL HR inserts, including tenant forms which do not use
    # advisory locks. Never depend on a legacy optional unique constraint.
    cursor.execute("LOCK TABLE hr.employee_profile IN SHARE ROW EXCLUSIVE MODE")
    cursor.execute(
        """SELECT id::text, central_user_id::text, email, is_deleted
             FROM hr.employee_profile
            WHERE central_user_id=%s OR lower(email)=lower(%s)
            FOR UPDATE""", [user_id, email],
    )
    rows = cursor.fetchall()
    if len(rows) > 1:
        raise RegistrationRejected("ambiguous", "일치하는 직원이 여러 명입니다. 테넌트에서 중복 정보를 확인하세요.")
    if rows:
        employee_id, linked_user_id, employee_email, deleted = rows[0]
        if deleted:
            raise RegistrationRejected("deleted", "삭제된 직원입니다. 테넌트에서 복구한 후 다시 등록하세요.")
        if linked_user_id and linked_user_id != user_id:
            raise RegistrationRejected("linked_elsewhere", "이미 다른 중앙 계정과 연결된 직원입니다.")
        if str(employee_email or "").strip().lower() != email.lower():
            raise RegistrationRejected("email_mismatch", "연결된 직원과 계정 이메일이 다릅니다. 테넌트에서 확인하세요.")
        if not linked_user_id:
            cursor.execute(
                "UPDATE hr.employee_profile SET central_user_id=%s, updated_at=now() WHERE id=%s",
                [user_id, employee_id],
            )
        return employee_id
    if not name:
        raise RegistrationRejected("name_required", "새 직원의 이름을 입력하세요.")
    employee_id = str(uuid4())
    cursor.execute(
        """INSERT INTO hr.employee_profile
               (id, central_user_id, email, name, status, is_deleted, created_at, updated_at)
           VALUES (%s, %s, %s, %s, '재직', false, now(), now())""",
        [employee_id, user_id, email, name],
    )
    return employee_id


def register_tenant_employee(*, user_id, group_id, role_id, actor_user_id, name=""):
    user_id, group_id, role_id, actor_user_id = (
        str(UUID(str(value))) for value in (user_id, group_id, role_id, actor_user_id)
    )
    name = str(name or "").strip()
    if len(name) > 200:
        raise RegistrationRejected("name_length", "직원 이름은 200자 이내로 입력하세요.")
    operation_id = str(uuid4())
    # Persist the attempt BEFORE touching the tenant. No distributed rollback is
    # claimed. A crash/ambiguous commit remains pending/failed, never completed.
    with transaction.atomic(using="default", durable=True):
        with connections["default"].cursor() as cur:
            cur.execute(
                """SELECT id FROM users WHERE id=%s AND is_staff=TRUE
                       AND is_active=TRUE AND email_verified=TRUE FOR SHARE""",
                [actor_user_id],
            )
            if not cur.fetchone():
                raise RegistrationRejected("forbidden", "중앙 관리자만 직원을 등록할 수 있습니다.")
            cur.execute(
                """INSERT INTO tenant_employee_registrations
                       (id, user_id, group_id, role_id, actor_user_id, status)
                   VALUES (%s, %s, %s, %s, %s, 'pending')""",
                [operation_id, user_id, group_id, role_id, actor_user_id],
            )

    def before_assign(cur, eligible):
        cur.execute(
            """SELECT u.email, u.name_display, r.code
                 FROM users u CROSS JOIN roles r WHERE u.id=%s AND r.id=%s""",
            [user_id, role_id],
        )
        email, display_name, role_code = cur.fetchone()
        try:
            _normalize_role_code(role_code)
        except (ValueError, TenantRoleRequestRejected):
            raise RegistrationRejected("role_forbidden", "테넌트에서 사용할 수 있는 역할을 선택하세요.") from None
        email = str(email or "").strip().lower()
        if not email:
            raise RegistrationRejected("email_required", "중앙 계정의 이메일을 확인하세요.")
        # Reuse GroupDBConfig -> Secrets Manager, never a posted DB alias or a
        # central administrator's current tenant session.
        with tenant_cursor(group_id, write=True) as tenant:
            employee_id = register_employee_profile(
                tenant, user_id=user_id, email=email, name=name or str(display_name or "").strip(),
            )
        cur.execute(
            """UPDATE tenant_employee_registrations
                  SET employee_id=%s, status='completed', updated_at=now()
                WHERE id=%s""", [employee_id, operation_id],
        )

    try:
        # Journal completion and role assignment commit together, only AFTER the
        # tenant transaction commits. Existing HR data never confers access.
        if not assign_group_role(user_id, group_id, role_id, before_assign=before_assign):
            raise RegistrationRejected("ineligible", "활성화된 계정·테넌트·역할인지 확인하세요.")
    except Exception as exc:
        # Fixed codes only: never log SQL, credentials or employee records.
        code = exc.code if isinstance(exc, RegistrationRejected) else "storage_error"
        try:
            with connections["default"].cursor() as cur:
                cur.execute(
                    """UPDATE tenant_employee_registrations
                          SET status='failed', error_code=%s, updated_at=now()
                        WHERE id=%s AND status='pending'""", [code, operation_id],
                )
        except Exception:
            pass  # Durable pending attempt is retained for reconciliation.
        if isinstance(exc, RegistrationRejected):
            raise
        raise RegistrationRejected(
            "storage_error",
            "등록 완료를 확인하지 못했습니다. 직원이 일부 저장됐을 수 있으니 같은 테넌트와 역할로 다시 시도하세요.",
        ) from None
    return operation_id
