"""Read-only production history audit; emits only repository migration identifiers."""
import os
import subprocess
import sys
from pathlib import Path


def missing_dependencies(graph, applied, replacements):
    """Match Django history checks, including fully applied squash replacements."""
    gaps = []
    for child in sorted(set(applied) & set(graph.node_map)):
        for parent in sorted(node.key for node in graph.node_map[child].parents):
            if parent in applied:
                continue
            if parent in replacements and all(item in applied for item in replacements[parent].replaces):
                continue
            gaps.append((child, parent))
    return gaps


def main():
    unit = 'geoflow-stabilized.service'
    def property_value(name):
        return subprocess.check_output(['systemctl', 'show', unit, '-p', name, '--value'], text=True).strip()
    if property_value('ActiveState') != 'active':
        raise RuntimeError('service_not_active')
    root = Path(property_value('WorkingDirectory')).resolve()
    if not (root / 'manage.py').is_file():
        raise RuntimeError('runtime_missing')
    os.chdir(root)
    sys.path.insert(0, str(root))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'geoflow_project.settings')
    import django
    django.setup()
    from django.db import connections, transaction
    from django.db.migrations.loader import MigrationLoader
    from control.models import GroupDBConfig
    from control.services.gis_admin import tenant_cursor
    loader = MigrationLoader(None)
    # Read-only at the database transaction boundary, including central discovery.
    with transaction.atomic(using='default'), connections['default'].cursor() as cursor:
        cursor.execute('SET TRANSACTION READ ONLY')
        cursor.execute("SET LOCAL statement_timeout='15s'")
        configs = list(GroupDBConfig.objects.using('default').filter(group__status='active')
                       .exclude(db_alias='default').order_by('group_id'))
    eligible = []
    for config in configs:
        with tenant_cursor(config.group_id, write=False) as cursor:
            cursor.execute("SELECT to_regclass('ops.my_org_units'), to_regclass('django_migrations')")
            if not all(cursor.fetchone()):
                continue
            cursor.execute('SELECT app,name FROM django_migrations')
            applied = set(cursor.fetchall())
            if ('webgisapp', '0048_gis_project_reference_groups') in applied:
                eligible.append(applied)
    print(f'company_history_eligible_count={len(eligible)}')
    if len(eligible) != 1:
        raise RuntimeError('ambiguous_target')
    applied = eligible[0]
    gaps = missing_dependencies(loader.graph, applied, loader.replacements)
    print(f'company_history_missing_dependency_count={len(gaps)}')
    for child, parent in gaps:
        # Both names originate from the checked-in migration graph, not user data.
        print('company_history_gap applied=' + '.'.join(child) + ' missing=' + '.'.join(parent))
    known = set(loader.graph.node_map)
    for app, name in sorted(known - applied):
        if app == 'webgisapp':
            print(f'company_history_unapplied={app}.{name}')
    print('company_history_audit_complete=yes database_writes=no service_restart=no')


if __name__ == '__main__':
    try:
        main()
    except Exception:
        # Never expose runtime paths, connection strings or raw exception messages.
        print('company_history_audit_failed=yes private_details_suppressed=yes')
        sys.exit(1)
