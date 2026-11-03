"""Read-only preflight. stdout is PRIVATE JSON; the workflow encrypts it, never logs it."""
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path


def analyze(contracts, projects):
    """Describe proposed changes; never apply them or infer runtime modes."""
    by_id = {c['id']: c for c in contracts}
    linked = defaultdict(list)
    orphans = []
    for p in projects:
        if p['contract_id'] not in by_id:
            orphans.append(p['id'])
        else:
            linked[p['contract_id']].append(p)
    blockers, changes, unrecognized = [], [], []
    multiple = [cid for cid, rows in linked.items() if len(rows) > 1]
    zero = [cid for cid in by_id if not linked[cid]]
    if multiple:
        blockers.append('existing_multiple_projects')
    if orphans:
        blockers.append('unlinked_or_orphan_projects')
    if zero:
        blockers.append('contracts_without_project_require_review')
    codes = Counter(p['code'] for p in projects if p['code'])
    contract_codes = Counter(c['code'] for c in contracts if c['code'])
    if any(n > 1 for n in codes.values()):
        blockers.append('duplicate_project_codes')
    if any(n > 1 for n in contract_codes.values()):
        blockers.append('duplicate_contract_codes')
    for c in contracts:
        ext = c['ext']
        if ext is not None and not isinstance(ext, dict):
            blockers.append('non_object_contract_ext')
            continue
        if isinstance(ext, dict) and 'project_mode' in ext:
            blockers.append('existing_project_mode_requires_review')
        if not c['code'] or c['code'] != c['code'].strip():
            blockers.append('missing_or_untrimmed_contract_code')
            continue
        if len(linked[c['id']]) != 1:
            continue
        p = linked[c['id']][0]
        proposed = c['code'] + '-001'
        legacy = 'C' + c['code'].strip().replace('-', '')
        recognized = p['code'] in (legacy, proposed)
        if not recognized:
            unrecognized.append(p['id'])
        if any(other['id'] != p['id'] and other['code'] == proposed for other in projects):
            blockers.append('proposed_code_collision')
        changes.append({
            'contract_id': c['id'], 'project_id': p['id'],
            'contract_code': c['code'], 'before_code': p['code'], 'after_code': proposed,
            'before_name': p['name'], 'after_name': c['name'],
            'name_differs': p['name'] != c['name'], 'code_differs': p['code'] != proposed,
            'legacy_automatic_code': p['code'] == legacy,
            'recognized_code': recognized,
        })
    if unrecognized:
        blockers.append('unrecognized_project_code_requires_review')
    if any(row['name_differs'] for row in changes):
        blockers.append('name_changes_require_semantic_review')
    proposed_codes = Counter(row['after_code'] for row in changes)
    if any(n > 1 for n in proposed_codes.values()):
        blockers.append('proposed_code_collision')
    return {
        'counts': {'contracts': len(contracts), 'projects': len(projects),
                   'zero_project_contracts': len(zero), 'multiple_project_contracts': len(multiple),
                   'orphan_projects': len(orphans),
                   'name_mismatches': sum(r['name_differs'] for r in changes),
                   'code_changes': sum(r['code_differs'] for r in changes),
                   'unrecognized_codes': len(unrecognized)},
        'contract_project_counts': {cid: len(linked[cid]) for cid in by_id},
        'status_counts': dict(Counter(p['status'] for p in projects)),
        'changes': changes, 'orphan_project_ids': orphans,
        'blockers': sorted(set(blockers)),
    }


def read_rows(cursor, query):
    cursor.execute(query)
    names = [col[0] for col in cursor.description]
    rows = cursor.fetchmany(20001)
    if len(rows) > 20000:
        raise RuntimeError('audit_row_limit_exceeded')
    return [dict(zip(names, row)) for row in rows]


def inspect(cursor):
    cursor.execute("SELECT to_regclass('ctr.contracts'), to_regclass('prj.projects')")
    present = cursor.fetchone()
    if not any(present):
        return {'classification': 'no_contract_project_schema'}
    if not all(present):
        return {'classification': 'partial_schema', 'blockers': ['partial_schema']}
    contracts = read_rows(cursor, 'SELECT id::text, code, name, ext FROM ctr.contracts ORDER BY id')
    projects = read_rows(cursor, '''SELECT id::text, contract_id::text, code, name,
        status, start_date, end_date, created_at, updated_at FROM prj.projects ORDER BY id''')
    report = analyze(contracts, projects)
    report['classification'] = 'contract_project_tenant'
    report['contracts'] = [{k: v for k, v in c.items() if k != 'ext'} |
                           {'ext_type': type(c['ext']).__name__,
                            'ext_keys': sorted(c['ext']) if isinstance(c['ext'], dict) else []}
                           for c in contracts]
    report['projects'] = projects
    report['constraints'] = read_rows(cursor, '''SELECT conrelid::regclass::text AS relation,
        conname AS name, contype AS kind, pg_get_constraintdef(oid) AS definition
        FROM pg_constraint WHERE conrelid IN ('ctr.contracts'::regclass,'prj.projects'::regclass)
        OR confrelid IN ('ctr.contracts'::regclass,'prj.projects'::regclass)
        ORDER BY conrelid,conname''')
    report['indexes'] = read_rows(cursor, '''SELECT schemaname,tablename,indexname,indexdef
        FROM pg_indexes WHERE (schemaname='ctr' AND tablename='contracts')
        OR (schemaname='prj' AND tablename='projects') ORDER BY schemaname,indexname''')
    report['triggers'] = read_rows(cursor, '''SELECT tgrelid::regclass::text AS relation,
        tgname AS name, pg_get_triggerdef(oid) AS definition,
        tgfoid::regprocedure::text AS function, pg_get_functiondef(tgfoid) AS function_definition
        FROM pg_trigger WHERE NOT tgisinternal
        AND tgrelid IN ('ctr.contracts'::regclass,'prj.projects'::regclass) ORDER BY tgrelid,tgname''')
    report['columns'] = read_rows(cursor, '''SELECT table_schema,table_name,column_name,
        data_type,is_nullable,column_default FROM information_schema.columns
        WHERE (table_schema='ctr' AND table_name='contracts')
        OR (table_schema='prj' AND table_name='projects') ORDER BY table_schema,ordinal_position''')
    # Constraints/triggers must be reviewed, not automatically labelled safe.
    report['metadata_review_required'] = True
    return report


def main():
    def prop(name):
        return subprocess.check_output(['systemctl','show','geoflow-stabilized.service',
                                        '-p',name,'--value'], text=True).strip()
    if prop('ActiveState') != 'active':
        raise RuntimeError('service_not_active')
    root = Path(prop('WorkingDirectory')).resolve()
    if not (root / 'manage.py').is_file():
        raise RuntimeError('runtime_missing')
    os.chdir(root)
    sys.path.insert(0, str(root))
    os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'geoflow_project.settings')
    import django
    django.setup()
    import psycopg2
    from django.db import connections, transaction
    from control.models import GroupDBConfig
    from control.services.tenant_db_secret_resolver import resolve_tenant_db_password
    with transaction.atomic(using='default'), connections['default'].cursor() as cur:
        cur.execute('SET TRANSACTION READ ONLY')
        cur.execute("SET LOCAL statement_timeout='15s'")
        configs = list(GroupDBConfig.objects.using('default').filter(group__status='active')
                       .exclude(db_alias='default').order_by('group_id'))
    report = {'version': 1, 'read_only': True,
              'captured_at': datetime.now(timezone.utc).isoformat(),
              'runtime_sha': subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
              'tenants': []}
    for config in configs:
        password = resolve_tenant_db_password(str(config.db_password or '').strip())
        conn = psycopg2.connect(dbname=config.db_name, user=config.db_user, password=password,
                               host=config.db_host, port=config.db_port, sslmode='require',
                               connect_timeout=10, application_name='geoflow_contract_project_audit')
        try:
            conn.set_session(readonly=True, isolation_level='REPEATABLE READ', autocommit=False)
            with conn.cursor() as cur:
                cur.execute("SET LOCAL statement_timeout='20s'")
                cur.execute("SET LOCAL lock_timeout='3s'")
                cur.execute('SELECT current_database()')
                if cur.fetchone()[0] != config.db_name:
                    raise RuntimeError('tenant_identity_mismatch')
                result = inspect(cur)
            result['group_id'] = str(config.group_id)
            report['tenants'].append(result)
        finally:
            conn.rollback()
            conn.close()
    if not report['tenants']:
        raise RuntimeError('no_active_tenant_configurations')
    print(json.dumps(report, ensure_ascii=False, default=str))


if __name__ == '__main__':
    try:
        main()
    except Exception:
        print('contract_project_audit_failed=yes details_suppressed=yes', file=sys.stderr)
        sys.exit(1)
