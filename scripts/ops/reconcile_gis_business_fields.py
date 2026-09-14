"""Plan by default. Uses the existing central locator/Secrets Manager path."""
import argparse
import json
import os
import subprocess
from pathlib import Path
from uuid import UUID
from sync_gis_catalog_capability_bindings import _connect_tenant, _one

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
    args = parser.parse_args()
    config = _locate(args.group_code, args.db_alias)
    from geoflow_ops.gis.business_fields import inspect_contract, plan_contract, reconcile, ContractConflict, TABLES
    conn = _connect_tenant(config)
    try:
        with conn.cursor() as cur:
            cur.execute('SET TRANSACTION READ ONLY')
            cur.execute("SET LOCAL statement_timeout='30s'")
            state = inspect_contract(cur, args.project_id)
            # Evidence remains available even when the planner finds conflicts.
            print(json.dumps({'database': config.db_name, 'inspection': state}, default=str, ensure_ascii=False))
            operations = plan_contract(state)
        conn.rollback()
        print(json.dumps({'database': config.db_name, 'profile': state['profile'], 'operations':len(operations), 'plan':[{'sql':sql,'parameters':params} for sql,params in operations]}, default=str, ensure_ascii=False))
        if not args.apply:
            return 0
        if not args.backup_dir:
            parser.error('--apply requires --backup-dir; maintenance write freeze required')
        args.backup_dir.mkdir(parents=True,exist_ok=True)
        archive = args.backup_dir / 'gis-before-business-fields.dump'
        if archive.exists():
            raise RuntimeError('Backup already exists; use a fresh backup directory')
        # libpq connection details stay in subprocess environment, never argv/logs.
        from psycopg2.extensions import parse_dsn
        dsn = parse_dsn(conn.dsn)
        env = dict(os.environ)
        for key, variable in [('dbname','PGDATABASE'),('host','PGHOST'),('port','PGPORT'),('user','PGUSER'),('password','PGPASSWORD'),('sslmode','PGSSLMODE')]:
            if key in dsn: env[variable]=dsn[key]
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
            count = reconcile(cur,args.project_id)
        conn.commit()
        print(json.dumps({'applied_operations':count,'verified':True}))
        return 0
    except ContractConflict as exc:
        conn.rollback()
        print(json.dumps({'conflicts':exc.conflicts,'applied':False},default=str,ensure_ascii=False))
        return 2
    finally:
        conn.close()


if __name__=='__main__':
    raise SystemExit(main())
