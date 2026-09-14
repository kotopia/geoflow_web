"""Plan by default. Uses the existing central locator/Secrets Manager path."""
import argparse
import json
import os
import subprocess
from pathlib import Path
from uuid import UUID
from sync_gis_catalog_capability_bindings import _connect_tenant, _one


def _backup_environment(config, connection):
    from psycopg2.extensions import parse_dsn
    from control.services.tenant_db_secret_resolver import (
        is_tenant_db_secret_reference, resolve_tenant_db_password,
    )
    # connection.dsn masks passwords. Preserve its target/SSL, resolve the
    # credential through the same tenant resolver used for the connection.
    dsn = parse_dsn(connection.dsn)
    env = dict(os.environ)
    for key, variable in [('dbname','PGDATABASE'),('host','PGHOST'),('port','PGPORT'),('user','PGUSER'),('sslmode','PGSSLMODE')]:
        if key in dsn:
            env[variable] = dsn[key]
    reference = str(config.db_password or '').strip()
    password = resolve_tenant_db_password(reference) if is_tenant_db_secret_reference(reference) else reference
    if not password:
        raise RuntimeError('Target tenant database password is empty')
    env['PGPASSWORD'] = password
    return env

def _locate(group_code, db_alias):
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")
    import django
    django.setup()
    from django.db import connections, transaction
    from control.models import GroupDBConfig
    with transaction.atomic(using="default"):
        with connections["default"].cursor() as cur:
            cur.execute("SET LOCAL TRANSACTION READ ONLY")
            cur.execute("SET LOCAL statement_timeout='15s'")
            rows=list(GroupDBConfig.objects.using("default").select_related("group").filter(group__code=group_code,db_alias=db_alias))
    config=_one(rows,"target tenant database configuration")
    if str(config.group.status).lower() != "active":
        raise RuntimeError("target tenant group is not active")
    return config



def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--group-code', required=True)
    parser.add_argument('--db-alias', required=True)
    parser.add_argument('--project-id', required=True, type=UUID)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-dir', type=Path)
    parser.add_argument('--approval-file', type=Path)
    parser.add_argument('--approval-sha256')
    parser.add_argument('--export-approval', type=Path)
    parser.add_argument('--messages-file', type=Path)
    args = parser.parse_args()
    if args.apply and (not args.approval_file or not args.approval_sha256 or args.export_approval):
        parser.error('--apply requires an independently reviewed --approval-file and --approval-sha256; cannot export and apply together')
    if args.export_approval and not args.messages_file:
        parser.error('--export-approval requires the original --messages-file for operational ID cross-check')
    from geoflow_ops.gis.business_approval import load_approval, build_approval, guarded_reconcile, ApprovalRejected
    approval = load_approval(args.approval_file,args.approval_sha256) if args.apply else None
    if args.apply and not approval.get('evidence',{}).get('verified'):
        parser.error('Approval must include a verified original Messages cross-check')
    config = _locate(args.group_code, args.db_alias)
    from geoflow_ops.gis.business_fields import inspect_contract, plan_contract, ContractConflict, TABLES
    context = dict(database=config.db_name,group_code=args.group_code,db_alias=args.db_alias,
                   project_id=str(args.project_id),project_code='26003')
    conn = _connect_tenant(config)
    try:
        with conn.cursor() as cur:
            cur.execute('SET TRANSACTION READ ONLY')
            cur.execute("SET LOCAL statement_timeout='30s'")
            state = inspect_contract(cur, args.project_id)
            # Evidence remains available even when the planner finds conflicts.
            print(json.dumps({'database': config.db_name, 'inspection': state}, default=str, ensure_ascii=False))
            operations = plan_contract(state)
            if args.export_approval:
                candidate = build_approval(cur,args.project_id,context)
                from geoflow_ops.gis.business_messages import verify_messages
                candidate['evidence'] = verify_messages(args.messages_file.read_bytes(),candidate)
                with args.export_approval.open('x',encoding='utf-8') as handle:
                    json.dump(candidate,handle,ensure_ascii=False,indent=2)
        conn.rollback()
        print(json.dumps({'database': config.db_name, 'profile': state['profile'], 'operations':len(operations), 'plan':[{'sql':sql,'parameters':params} for sql,params in operations]}, default=str, ensure_ascii=False))
        if not args.apply:
            return 0
        if not operations:
            # A zero plan alone is insufficient: require exact approved post-state under locks.
            with conn.cursor() as cur:
                cur.execute("SET LOCAL lock_timeout='5s'")
                cur.execute("SET LOCAL statement_timeout='60s'")
                count = guarded_reconcile(cur,args.project_id,approval,context,allow_changes=False)
            conn.rollback()
            print(json.dumps({'applied_operations':count,'verified':True,'already_applied':True}))
            return 0
        if not args.backup_dir:
            parser.error('--apply requires --backup-dir; maintenance write freeze required')
        args.backup_dir.mkdir(parents=True,exist_ok=True)
        archive = args.backup_dir / 'gis-before-business-fields.dump'
        if archive.exists():
            raise RuntimeError('Backup already exists; use a fresh backup directory')
        # libpq connection details stay in subprocess environment, never argv/logs.
        env = _backup_environment(config, conn)
        backup_tables = (*TABLES, 'meta_field_def', 'profile_field')
        result = subprocess.run(['pg_dump','--format=custom',
                                 *['--table=gis.' + table for table in backup_tables],
                                 '--file',str(archive)],env=env,capture_output=True)
        if result.returncode or not archive.is_file() or not archive.stat().st_size:
            raise RuntimeError('Backup failed; no changes applied')
        (args.backup_dir/'metadata-before.json').write_text(json.dumps(state,default=str,ensure_ascii=False,indent=2),encoding='utf-8')
        with conn.cursor() as cur:
            cur.execute("SET LOCAL lock_timeout='5s'")
            cur.execute("SET LOCAL statement_timeout='60s'")
            count = guarded_reconcile(cur,args.project_id,approval,context)
        conn.commit()
        print(json.dumps({'applied_operations':count,'verified':True}))
        return 0
    except ApprovalRejected:
        conn.rollback()
        print(json.dumps({'approval_rejected':True,'applied':False}))
        return 2
    except ContractConflict as exc:
        conn.rollback()
        print(json.dumps({'conflicts':exc.conflicts,'applied':False},default=str,ensure_ascii=False))
        return 2
    finally:
        conn.close()


if __name__=='__main__':
    raise SystemExit(main())
