"""Snapshot-guarded one-time policy initialization; no DDL or UUID changes.

The deployment gate supplies authorization. All tenants are validated and backed
up before the first commit; a partial cross-DB commit is safe to retry.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()


def signature(rows):
    return digest(sorted([[r['contract_id'], r['project_id'], r['contract_code'], r['contract_name'],
                           r['project_code'], r['project_name']] for r in rows]))


def read_rows(cursor):
    cursor.execute('''SELECT c.id::text AS contract_id, p.id::text AS project_id,
        c.code AS contract_code, c.name AS contract_name,
        p.code AS project_code, p.name AS project_name,
        to_jsonb(c) AS contract_record, to_jsonb(p) AS project_record
        FROM ctr.contracts c FULL JOIN prj.projects p ON p.contract_id=c.id ORDER BY c.id,p.id''')
    names = [c[0] for c in cursor.description]
    rows = cursor.fetchmany(20001)
    if len(rows) > 20000:
        raise RuntimeError('row_limit_exceeded')
    result = [dict(zip(names, row)) for row in rows]
    for row in result:
        for key in ('contract_record', 'project_record'):
            if isinstance(row[key], str):
                row[key] = json.loads(row[key])
    return result


def validate(rows, target):
    if len(rows) != target['count'] or any(not r['contract_id'] or not r['project_id'] for r in rows):
        raise RuntimeError('relationships_changed')
    if len({r['contract_id'] for r in rows}) != len(rows):
        raise RuntimeError('multiple_projects_found')
    done = signature(rows) == target['after']
    if signature(rows) not in (target['before'], target['after']):
        raise RuntimeError('snapshot_changed')
    codes = [r['contract_code'] + '-001' for r in rows]
    if len(set(codes)) != len(codes) or any(not r['contract_code'] for r in rows):
        raise RuntimeError('invalid_contract_codes')
    for row in rows:
        ext = row['contract_record']['ext']
        if not isinstance(ext, dict):
            raise RuntimeError('invalid_ext')
        if done:
            if ext.get('project_mode') != 'SINGLE' or ext.get('project_sequence') != 1:
                raise RuntimeError('partial_policy_state')
        elif 'project_mode' in ext or 'project_sequence' in ext:
            raise RuntimeError('policy_already_changed')
    return done


def prepare(conn, target):
    with conn.cursor() as cursor:
        cursor.execute("SET LOCAL lock_timeout='3s'")
        cursor.execute("SET LOCAL statement_timeout='30s'")
        cursor.execute('LOCK TABLE ctr.contracts, prj.projects IN SHARE ROW EXCLUSIVE MODE')
        cursor.execute('''SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal
            AND tgrelid IN ('ctr.contracts'::regclass,'prj.projects'::regclass)''')
        if cursor.fetchone()[0]:
            raise RuntimeError('unexpected_trigger')
        cursor.execute('''SELECT conrelid::regclass::text, conname, contype, pg_get_constraintdef(oid)
            FROM pg_constraint WHERE conrelid IN ('ctr.contracts'::regclass,'prj.projects'::regclass)
            OR confrelid IN ('ctr.contracts'::regclass,'prj.projects'::regclass)
            ORDER BY conrelid::regclass::text,conname''')
        constraints = [list(r) for r in cursor.fetchall()]
        if digest(sorted(constraints)) != target['constraints']:
            raise RuntimeError('constraints_changed')
        cursor.execute("""SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes
            WHERE (schemaname='ctr' AND tablename='contracts')
               OR (schemaname='prj' AND tablename='projects')""")
        if digest(sorted([list(r) for r in cursor.fetchall()])) != target['indexes']:
            raise RuntimeError('indexes_changed')
        rows = read_rows(cursor)
        return rows, validate(rows, target)


def apply(conn, rows, target):
    with conn.cursor() as cursor:
        for row in rows:
            ext = {**row['contract_record']['ext'], 'project_mode': 'SINGLE', 'project_sequence': 1}
            cursor.execute('UPDATE ctr.contracts SET ext=%s::jsonb WHERE id=%s',
                           [json.dumps(ext), row['contract_id']])
            cursor.execute('''UPDATE prj.projects SET name=%s,code=%s,updated_at=clock_timestamp()
                WHERE id=%s AND contract_id=%s''',
                           [row['contract_name'], row['contract_code']+'-001', row['project_id'], row['contract_id']])
        after = read_rows(cursor)
        if not validate(after, target):
            raise RuntimeError('verification_failed')
        before_by_id = {r['project_id']: r for r in rows}
        for row in after:
            original = before_by_id[row['project_id']]
            for record, allowed in [('project_record', {'name','code','updated_at'}), ('contract_record', {'ext'})]:
                if any(row[record][k] != v for k,v in original[record].items() if k not in allowed):
                    raise RuntimeError('unrelated_fields_changed')
            original_ext = original['contract_record']['ext']
            if any(row['contract_record']['ext'].get(k) != v for k,v in original_ext.items()):
                raise RuntimeError('ext_not_preserved')


def encrypted_backup(data, certificate, run_id):
    base = Path('/var/tmp/geoflow-contract-project-policy')
    base.mkdir(mode=0o700, exist_ok=True)
    if base.is_symlink() or base.stat().st_uid != os.getuid() or base.stat().st_mode & 0o077:
        raise RuntimeError('unsafe_backup_directory')
    import tempfile
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        cert = Path(tmp)/'recipient.pem'
        cert.write_text(certificate)
        encrypted = subprocess.run(['openssl','cms','-encrypt','-binary','-aes-256-cbc','-outform','DER',str(cert)],
                                   input=json.dumps(data,ensure_ascii=False).encode(),capture_output=True,check=True).stdout
    if not encrypted:
        raise RuntimeError('empty_backup')
    fd = os.open(base/(run_id+'.cms'), os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(fd,'wb') as out:
        out.write(encrypted); out.flush(); os.fsync(out.fileno())
    fd = os.open(base,os.O_RDONLY|os.O_DIRECTORY)
    try: os.fsync(fd)
    finally: os.close(fd)


def run(run_id):
    conns = []
    try:
        if not run_id.replace('-','').isdigit():
            raise RuntimeError('invalid_run_id')
        root = Path(__file__).resolve().parents[2]
        manifest = json.loads((root/'deploy/contracts/project-policy.json').read_text())
        cert = (root/'deploy/contracts/audit-recipient.pem').read_text()
        sys.path.insert(0,str(root))
        os.environ.setdefault('DJANGO_SETTINGS_MODULE','geoflow_project.settings')
        import django; django.setup()
        import psycopg2
        from django.db import connections, transaction
        from control.models import GroupDBConfig
        from control.services.tenant_db_secret_resolver import resolve_tenant_db_password
        with transaction.atomic(using='default'), connections['default'].cursor() as cur:
            cur.execute('SET TRANSACTION READ ONLY')
            configs = list(GroupDBConfig.objects.using('default').filter(group__status='active').exclude(db_alias='default'))
        if {digest(str(c.group_id)) for c in configs} != set(manifest['tenants']):
            raise RuntimeError('tenant_set_changed')
        prepared = []
        for config in sorted(configs,key=lambda c:str(c.group_id)):
            target = manifest['tenants'][digest(str(config.group_id))]
            conn = psycopg2.connect(dbname=config.db_name,user=config.db_user,
                password=resolve_tenant_db_password(str(config.db_password or '').strip()),
                host=config.db_host,port=config.db_port,sslmode='require',connect_timeout=10,
                application_name='geoflow_contract_project_policy')
            conns.append(conn)
            rows, done = prepare(conn,target)
            prepared.append((conn,rows,target,done))
        pending = [item for item in prepared if not item[3]]
        if pending:
            encrypted_backup({'tenants':[{'target':t,'rows':r} for c,r,t,d in pending]},cert,run_id)
        for conn, rows, target, done in pending:
            apply(conn,rows,target)
        # No distributed transaction: all validation/update succeeds before the
        # commit loop. A failed commit blocks deployment; retry accepts before/after.
        for conn,rows,target,done in prepared:
            conn.commit()
        for conn,rows,target,done in prepared:
            with conn.cursor() as cur:
                cur.execute('SET TRANSACTION READ ONLY')
                if not validate(read_rows(cur),target):
                    raise RuntimeError('post_commit_verification_failed')
            conn.rollback()
        print(json.dumps({'tenants_verified':len(prepared),'projects_converted':sum(len(r) for c,r,t,d in pending),
                          'projects_verified':sum(len(r) for c,r,t,d in prepared),'uuid_changes':0,'schema_changes':0}))
    except Exception:
        print('contract_project_policy_activation_failed=yes details_suppressed=yes',file=sys.stderr)
        raise SystemExit(1)
    finally:
        for conn in conns:
            conn.rollback(); conn.close()


if __name__ == '__main__':
    run(sys.argv[1])
