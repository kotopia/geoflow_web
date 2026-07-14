from django.db import connections
from control.middleware import current_db_alias


def topbar_user(request):
    """
    Topbar 전역 컨텍스트
    - 로그인 사용자의 이름/아바타 attachment id 제공
    - 세션 캐시 우선 사용
    - 예외는 외부로 전파하지 않음
    """
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {
            "topbar_user_name": "",
            "avatar_attachment_id": None,
        }

    fallback_email = (getattr(request.user, "email", "") or "").strip()

    try:
        cached_name = request.session.get("topbar_name")
        has_cached_avatar_key = "topbar_avatar_attachment_id" in request.session
        cached_avatar = request.session.get("topbar_avatar_attachment_id")

        if cached_name is not None and has_cached_avatar_key:
            return {
                "topbar_user_name": cached_name,
                "avatar_attachment_id": cached_avatar,
            }

        alias = current_db_alias()
        if not alias:
            return {
                "topbar_user_name": fallback_email,
                "avatar_attachment_id": None,
            }

        user_email = fallback_email
        if not user_email:
            return {
                "topbar_user_name": "",
                "avatar_attachment_id": None,
            }

        topbar_name = user_email
        avatar_attachment_id = None

        with connections[alias].cursor() as cur:
            cur.execute(
                """
                SELECT id::text, COALESCE(name, '')
                FROM hr.employee_profile
                WHERE lower(email) = lower(%s)
                LIMIT 1
                """,
                [user_email],
            )
            emp_row = cur.fetchone()

            if emp_row:
                employee_id = emp_row[0]
                employee_name = emp_row[1]
                topbar_name = employee_name or user_email

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
                att_row = cur.fetchone()

                if not att_row:
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
                    att_row = cur.fetchone()

                if att_row:
                    avatar_attachment_id = att_row[0]

        request.session["topbar_name"] = topbar_name
        request.session["topbar_avatar_attachment_id"] = avatar_attachment_id

        return {
            "topbar_user_name": topbar_name,
            "avatar_attachment_id": avatar_attachment_id,
        }

    except Exception:
        return {
            "topbar_user_name": fallback_email,
            "avatar_attachment_id": None,
        }
