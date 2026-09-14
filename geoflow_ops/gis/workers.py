"""GIS-only employee identity and assignment contract; no account mutations."""
from uuid import UUID
from django.conf import settings
from django.db import connections
from control.services_identity import lookup_user_id_from_request
from geoflow_ops.services.project_access import _login_identity, project_access_policy


def current_user_context(request, alias):
    central_id = lookup_user_id_from_request(request)
    display_name = None
    if central_id:
        with connections[getattr(settings, 'CENTRAL_DB_ALIAS', 'default')].cursor() as cur:
            cur.execute('SELECT name_display FROM users WHERE id=%s', [central_id])
            row = cur.fetchone()
            display_name = row[0] if row else None
    identity = _login_identity(request)
    rows = []
    if identity:
        with connections[alias].cursor() as cur:
            cur.execute('SELECT id::text, name FROM hr.employee_profile WHERE lower(email)=lower(%s) AND is_deleted=false LIMIT 2', [identity])
            rows = cur.fetchall()
    status = 'linked' if len(rows) == 1 else 'ambiguous' if rows else 'unlinked'
    employee_id, name = rows[0] if status == 'linked' else (None, None)
    return dict(user_id=central_id, display_name=display_name,
                employee_id=employee_id, worker_id=employee_id, worker_name=name,
                worker_link_status=status)


def project_workers(request, alias, project_id, plan):
    from .gpkg import _SAFE_IDENT
    current = current_user_context(request, alias)
    ids = {current['worker_id']} if current['worker_id'] else set()
    with connections[alias].cursor() as cur:
        for layer in plan.get('layers') or []:
            table = str(layer.get('physical_name') or '')
            if not _SAFE_IDENT.fullmatch(table):
                continue
            cur.execute("SELECT 1 FROM information_schema.columns WHERE table_schema='gis' AND table_name=%s AND column_name='worker_id'", [table])
            if not cur.fetchone():
                continue
            cur.execute(f'SELECT DISTINCT worker_id::text FROM gis."{table}" WHERE project_id=%s AND worker_id IS NOT NULL', [str(project_id)])
            ids.update(row[0] for row in cur.fetchall())
        if ids:
            cur.execute('SELECT id::text, name FROM hr.employee_profile WHERE id=ANY(%s::uuid[]) AND is_deleted=false', [sorted(ids)])
            names = dict(cur.fetchall())
        else:
            names = {}
    return current, [dict(id=value, name=names.get(value), resolved=value in names) for value in sorted(ids)]


def validate_worker_assignment(alias, project_id, operation, request=None):
    from .qgis_sync import SyncRejected
    if operation.action == 'delete' or 'worker_id' not in operation.attributes:
        return
    value = operation.attributes['worker_id']
    try:
        value = str(UUID(str(value))) if value not in (None, '') else None
    except (ValueError, TypeError, AttributeError):
        raise SyncRejected('worker_id: invalid UUID') from None
    if operation.action == 'update':
        # Preserve unchanged historical identifiers, including unresolved ones.
        with connections[alias].cursor() as cur:
            cur.execute(f'SELECT worker_id::text FROM gis."{operation.table}" WHERE project_id=%s AND id=%s FOR UPDATE', [project_id, operation.object_id])
            row = cur.fetchone()
        if row and row[0] == value:
            return
    if request is None:
        raise SyncRejected('worker_id: authenticated assignment context required')
    policy = project_access_policy(request, alias)
    if not policy.can_webgis_write(project_id):
        raise SyncRejected('worker_id: assignment denied')
    current = current_user_context(request, alias)
    manager = policy.can_edit_project(project_id)
    if value is None:
        if operation.action == 'create' or manager:
            return
        raise SyncRejected('worker_id: only project managers may clear an existing assignment')
    if not manager and (current['worker_link_status'] != 'linked' or value != current['worker_id']):
        raise SyncRejected('worker_id: only your linked employee may be assigned')
    with connections[alias].cursor() as cur:
        cur.execute('SELECT id FROM hr.employee_profile WHERE id=%s AND is_deleted=false FOR SHARE', [value])
        if not cur.fetchone():
            raise SyncRejected('worker_id: employee not available in this tenant')
