from django.db import connections
from control.middleware import current_db_alias

from .services.employee_access import employee_access_policy
from .services.tenant_settings import settings_options


def _employee_access_context(request, alias=None):
    base = {
        "employee_self_id": None,
        "employee_can_list": False,
        "employee_can_create": False,
        "employee_can_manage_settings": False,
    }
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return base
    try:
        alias = alias or current_db_alias()
        if not alias:
            return base
        policy = employee_access_policy(request, alias)
        return {
            "employee_self_id": policy.self_employee_id,
            "employee_can_list": policy.can_list,
            "employee_can_create": policy.can_create,
            "employee_can_manage_settings": policy.can_manage_settings,
        }
    except Exception:
        return base


def _tenant_vocabulary_context():
    """Small shared label map used by list/detail UI.

    Machine codes remain stable while tenant settings may rename their displayed
    labels. Fail back to the reviewed defaults if the tenant settings schema is
    not available in the current request scope.
    """
    try:
        alias = current_db_alias()
        if not alias:
            return {"gf_contract_status_labels": {}, "gf_contract_kind_labels": {}}
        return {
            "gf_contract_status_labels": dict(settings_options(alias, "contract.status")),
            "gf_contract_kind_labels": dict(settings_options(alias, "contract.kind")),
        }
    except Exception:
        return {"gf_contract_status_labels": {}, "gf_contract_kind_labels": {}}


def topbar_user(request):
    """Topbar and tenant navigation context.

    The employee access flags are calculated from the same server-side role policy
    used by employee routes; the sidebar therefore never becomes an independent
    authorization source.
    """
    access = _employee_access_context(request)
    vocabulary = _tenant_vocabulary_context()
    if not getattr(request, "user", None) or not request.user.is_authenticated:
        return {"topbar_user_name": "", "avatar_attachment_id": None, **access, **vocabulary}

    fallback_email = (getattr(request.user, "email", "") or "").strip()

    try:
        cached_name = request.session.get("topbar_name")
        has_cached_avatar_key = "topbar_avatar_attachment_id" in request.session
        cached_avatar = request.session.get("topbar_avatar_attachment_id")

        if cached_name is not None and has_cached_avatar_key:
            return {
                "topbar_user_name": cached_name,
                "avatar_attachment_id": cached_avatar,
                **access,
                **vocabulary,
            }

        alias = current_db_alias()
        if not alias:
            return {
                "topbar_user_name": fallback_email,
                "avatar_attachment_id": None,
                **access,
                **vocabulary,
            }

        user_email = fallback_email
        if not user_email:
            return {"topbar_user_name": "", "avatar_attachment_id": None, **access, **vocabulary}

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
                       AND purpose IN ('photo_thumb', 'thumb')
                       AND active = true
                       AND deleted_at IS NULL
                     ORDER BY ord, created_at DESC
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
                           AND deleted_at IS NULL
                         ORDER BY ord, created_at DESC
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
            **access,
            **vocabulary,
        }

    except Exception:
        return {
            "topbar_user_name": fallback_email,
            "avatar_attachment_id": None,
            **access,
            **vocabulary,
        }
