"""Central group menu preferences. Never an authorization policy."""
from uuid import UUID

from django.conf import settings
from django.db import connections

from control.services import central_repo as C


SERVICE_MENUS = (("bids", "입찰"), ("gis", "GIS"), ("finance", "파이낸스"))


def central_alias():
    return getattr(settings, "CENTRAL_DB_ALIAS", "default")


def settings_available():
    return C._table_exists(central_alias(), "group_service_menu_settings")


def get_service_menus(group_id, *, available=None):
    defaults = {code: True for code, _label in SERVICE_MENUS}
    if available is None:
        available = settings_available()
    # Rolling deployment compatibility only; remove after migration 0007 is
    # required everywhere. Missing rows intentionally preserve existing menus.
    if not available:
        return defaults
    with connections[central_alias()].cursor() as cursor:
        cursor.execute(
            "SELECT bids, gis, finance FROM group_service_menu_settings WHERE group_id=%s",
            [str(UUID(str(group_id)))],
        )
        row = cursor.fetchone()
    return dict(zip(defaults, map(bool, row))) if row else defaults


def save_service_menus(group_id, values):
    # Called only by the central-admin view within its metadata transaction.
    with connections[central_alias()].cursor() as cursor:
        cursor.execute(
            """INSERT INTO group_service_menu_settings (group_id, bids, gis, finance)
               VALUES (%s, %s, %s, %s)
               ON CONFLICT (group_id) DO UPDATE
                  SET bids=EXCLUDED.bids, gis=EXCLUDED.gis,
                      finance=EXCLUDED.finance, updated_at=now()""",
            [str(UUID(str(group_id)))] + [bool(values[code]) for code, _ in SERVICE_MENUS],
        )


def service_menu_context(request):
    from control.middleware import current_db_alias

    hidden = {code: False for code, _ in SERVICE_MENUS}
    session = getattr(request, "session", {})
    alias = current_db_alias()
    group_id = session.get("group_id") or session.get("group_uuid")
    if (not getattr(getattr(request, "user", None), "is_authenticated", False)
            or session.get("scope") != "tenant" or not group_id
            or not alias or alias == central_alias()
            or alias != session.get("tenant_db_alias")):
        return {"service_menus": hidden}
    # Keep decisions request-local: switching groups or changing central settings
    # takes effect on the next page load without stale session permissions.
    key = (alias, str(group_id))
    cached = getattr(request, "_gf_service_menu_visibility", None)
    if cached is None or cached[0] != key:
        cached = (key, get_service_menus(group_id))
        request._gf_service_menu_visibility = cached
    return {"service_menus": cached[1]}
