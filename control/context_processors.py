from django.db import connections
from control.services_identity import ensure_user_from_request
from control.services import central_repo as C
from control.middleware import current_db_alias

def central_flags(request):
    is_staff = False
    if getattr(request, "user", None) and request.user.is_authenticated:
        with connections["default"].cursor() as cur:
            cur.execute("SELECT is_staff FROM users WHERE email=%s LIMIT 1", [request.user.username])
            row = cur.fetchone()
            is_staff = bool(row and row[0])
    return {
        "central_is_staff": is_staff,
        "current_group_id": request.session.get("group_id"),
    }

def perms_context(request):
    """
    현재 그룹에서의 역할 전체만 템플릿에 주입.
    세션에 없으면 중앙에서 지연 로딩.
    """
    roles = request.session.get("roles")
    if roles is None:
        roles = []
        user_uuid = ensure_user_from_request(request)
        group_id  = request.session.get("group_uuid") or request.session.get("group_id")
        if user_uuid and group_id:
            try:
                roles = C.list_roles_for_user_in_group(user_uuid, group_id)
            except Exception:
                roles = []
        request.session["roles"] = roles

    return {"current_roles": roles}


def avatar_context(request):
    """
    로그인 사용자의 프로필 사진 attachment_id를 세션에서 가져와 템플릿에 주입.
    thumb 우선 -> photo 우선 -> None
    """
    avatar_att_id = request.session.get("avatar_attachment_id")

    # 세션에 없으면 DB에서 조회 (최초 1회)
    if avatar_att_id is None and request.user.is_authenticated:
        try:
            db_alias = current_db_alias()
            if not db_alias:
                return {"avatar_attachment_id": None}

            user_email = request.user.username

            with connections[db_alias].cursor() as cur:
                cur.execute(
                    """
                    SELECT id::text
                    FROM ops.employees
                    WHERE lower(email) = lower(%s)
                    AND active = true
                    LIMIT 1
                    """,
                    [user_email],
                )
                emp_row = cur.fetchone()

                if emp_row:
                    employee_id = emp_row[0]

                    cur.execute(
                        """
                        SELECT id::text
                        FROM ops.attachments
                        WHERE entity_type = 'employee'
                        AND entity_id::text = %s
                        AND purpose = 'thumb'
                        AND active = true
                        AND (deleted_at IS NULL OR is_deleted = false)
                        ORDER BY created_at DESC
                        LIMIT 1
                        """,
                        [employee_id],
                    )
                    thumb_row = cur.fetchone()

                    if thumb_row:
                        avatar_att_id = thumb_row[0]
                    else:
                        cur.execute(
                            """
                            SELECT id::text
                            FROM ops.attachments
                            WHERE entity_type = 'employee'
                            AND entity_id::text = %s
                            AND purpose = 'photo'
                            AND active = true
                            AND (deleted_at IS NULL OR is_deleted = false)
                            ORDER BY created_at DESC
                            LIMIT 1
                            """,
                            [employee_id],
                        )
                        photo_row = cur.fetchone()

                        if photo_row:
                            avatar_att_id = photo_row[0]

            request.session["avatar_attachment_id"] = avatar_att_id

        except Exception:
            avatar_att_id = None

    return {"avatar_attachment_id": avatar_att_id}