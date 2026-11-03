"""One-time, snapshot-guarded correction of four user-confirmed project names.

Production entry point is the protected workflow; no runtime application import.
The manifest contains only hashes, never production names or UUIDs.
"""
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode()).hexdigest()


def identity(group_id, contract_id, project_id):
    return digest([str(group_id), str(contract_id), str(project_id)])


def state(row):
    return digest([row['contract_code'], row['contract_name'],
                   row['project_code'], row['project_name']])


def select_targets(rows, group_id, manifest):
    expected = manifest['targets']
    if len(expected) != 4 or len({t['identity'] for t in expected}) != 4:
        raise RuntimeError('invalid_target_manifest')
    indexed = {identity(group_id, r['contract_id'], r['project_id']): r for r in rows}
    selected = []
    for target in expected:
        row = indexed.get(target['identity'])
        if row is None or row['project_count'] != 1:
            raise RuntimeError('target_relationship_changed')
        current = state(row)
        if current not in (target['before'], target['after']):
            raise RuntimeError('target_snapshot_changed')
        if not row['contract_name']:
            raise RuntimeError('empty_contract_name')
        selected.append((row, target, current == target['after']))
    return selected


def read_rows(cursor):
    cursor.execute('''SELECT c.id::text AS contract_id, p.id::text AS project_id,
        c.code AS contract_code, c.name AS contract_name,
        p.code AS project_code, p.name AS project_name,
        count(*) OVER (PARTITION BY c.id) AS project_count,
        to_jsonb(p) AS project_record
        FROM ctr.contracts c JOIN prj.projects p ON p.contract_id=c.id
        ORDER BY c.id,p.id''')
    names = [c[0] for c in cursor.description]
    rows = cursor.fetchmany(20001)
    if len(rows) > 20000:
        raise RuntimeError('row_limit_exceeded')
    return [dict(zip(names, row)) for row in rows]


def repair(conn, group_id, manifest, backup):
    """Lock, revalidate, durably back up, update atomically, and read back."""
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET LOCAL lock_timeout='3s'")
            cursor.execute("SET LOCAL statement_timeout='20s'")
            # Prevent concurrent edits/new children while checking cardinality.
            cursor.execute('LOCK TABLE ctr.contracts, prj.projects IN SHARE ROW EXCLUSIVE MODE')
            cursor.execute('''SELECT count(*) FROM pg_trigger WHERE NOT tgisinternal
                AND tgrelid IN ('ctr.contracts'::regclass,'prj.projects'::regclass)''')
            if cursor.fetchone()[0]:
                raise RuntimeError('unexpected_trigger')
            selected = select_targets(read_rows(cursor), group_id, manifest)
            pending = [(row, target) for row, target, done in selected if not done]
            if pending:
                backup({'group_id': str(group_id), 'targets': [r for r, _ in pending],
                        'manifest': manifest})
            for row, target in pending:
                cursor.execute('''UPDATE prj.projects AS p SET name=%s, updated_at=clock_timestamp()
                    WHERE id=%s AND contract_id=%s AND name IS NOT DISTINCT FROM %s
                    RETURNING to_jsonb(p)''',
                    (row['contract_name'], row['project_id'], row['contract_id'], row['project_name']))
                updated = cursor.fetchall()
                if len(updated) != 1:
                    raise RuntimeError('update_count_mismatch')
                after = updated[0][0]
                before = row['project_record']
                if after['name'] != row['contract_name'] or any(
                        after[k] != v for k, v in before.items() if k not in ('name', 'updated_at')):
                    raise RuntimeError('unexpected_field_change')
            verified = select_targets(read_rows(cursor), group_id, manifest)
            if not all(done for _, _, done in verified):
                raise RuntimeError('verification_failed')
        conn.commit()
        # Separate transaction verifies committed values; retry is idempotent.
        with conn.cursor() as cursor:
            cursor.execute('SET TRANSACTION READ ONLY')
            verified = select_targets(read_rows(cursor), group_id, manifest)
            if not all(done for _, _, done in verified):
                raise RuntimeError('post_commit_verification_failed')
        conn.rollback()
        return {'matched': 4, 'updated': len(pending), 'already_correct': 4-len(pending),
                'verified': 4, 'service_restart': False, 'code_changes': 0}
    except Exception:
        conn.rollback()
        raise


def encrypted_backup(data, certificate, run_id):
    """Persist encrypted before-values on the host BEFORE the first UPDATE."""
    base = Path('/var/tmp/geoflow-confirmed-project-names')
    base.mkdir(mode=0o700, exist_ok=True)
    if base.is_symlink() or base.stat().st_uid != os.getuid() or base.stat().st_mode & 0o077:
        raise RuntimeError('unsafe_backup_directory')
    import tempfile
    with tempfile.TemporaryDirectory(dir=base) as tmp:
        cert = Path(tmp) / 'recipient.pem'
        cert.write_text(certificate)
        encrypted = subprocess.run(['openssl', 'cms', '-encrypt', '-binary', '-aes-256-cbc',
                                    '-outform', 'DER', str(cert)],
                                   input=json.dumps(data, ensure_ascii=False).encode(),
                                   capture_output=True, check=True).stdout
    if not encrypted:
        raise RuntimeError('empty_backup')
    target = base / (run_id + '.cms')
    fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as out:
        out.write(encrypted)
        out.flush()
        os.fsync(out.fileno())
    directory_fd = os.open(base, os.O_RDONLY | os.O_DIRECTORY)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)


def run(manifest, certificate, run_id):
    try:
        if not run_id.replace('-', '').isdigit():
            raise RuntimeError('invalid_run_id')
        def prop(name):
            return subprocess.check_output(['systemctl','show','geoflow-stabilized.service',
                                            '-p',name,'--value'], text=True).strip()
        if prop('ActiveState') != 'active':
            raise RuntimeError('service_not_active')
        root = Path(prop('WorkingDirectory')).resolve()
        if not (root/'manage.py').is_file():
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
            configs = list(GroupDBConfig.objects.using('default').filter(group__status='active')
                           .exclude(db_alias='default'))
        targets = [c for c in configs if digest(str(c.group_id)) == manifest['group_sha256']]
        if len(targets) != 1:
            raise RuntimeError('tenant_identity_mismatch')
        c = targets[0]
        conn = psycopg2.connect(dbname=c.db_name, user=c.db_user,
                               password=resolve_tenant_db_password(str(c.db_password or '').strip()),
                               host=c.db_host, port=c.db_port, sslmode='require', connect_timeout=10,
                               application_name='geoflow_confirmed_project_names')
        try:
            with conn.cursor() as cur:
                cur.execute('SELECT current_database()')
                if cur.fetchone()[0] != c.db_name:
                    raise RuntimeError('database_identity_mismatch')
            conn.rollback()
            result = repair(conn, c.group_id, manifest,
                            lambda data: encrypted_backup(data, certificate, run_id))
            print(json.dumps(result))
        finally:
            conn.close()
    except Exception:
        # Never log a SQL exception containing business records or credentials.
        print('confirmed_project_name_repair_failed=yes details_suppressed=yes', file=sys.stderr)
        sys.exit(1)


if __name__ == '__main__' and len(sys.argv) > 1:
    # Build the reviewed stdin payload on the runner; no private values included.
    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root/'deploy/contracts/confirmed-project-names.json').read_text())
    cert = (root/'deploy/contracts/audit-recipient.pem').read_text()
    payload = Path(__file__).read_text() + '\nrun(' + repr(manifest) + ', ' + repr(cert) + ', ' + repr(sys.argv[1]) + ')\n'
    sys.stdout.write(payload)
