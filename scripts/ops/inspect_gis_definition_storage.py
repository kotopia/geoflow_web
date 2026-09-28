"""Export central + one explicitly selected tenant's structure, read-only.

Run from a checkout in the existing official service environment with PYTHONPATH=.
No migrations, application settings changes, secrets output, or apply option.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path


def write_private_report(path, report):
    payload = json.dumps(report, ensure_ascii=False, indent=2).encode("utf-8")
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, "O_NOFOLLOW", 0)
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "wb") as handle:
        handle.write(payload)


def collect(group_code, db_alias):
    if db_alias == "default":
        raise ValueError("Tenant alias must not be the central alias")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")
    import django
    django.setup()
    from django.db import connections, transaction
    from control.models import GroupDBConfig
    from diagnose_gis_project_readiness import _connect_tenant
    from geoflow_ops.gis.definition_inventory import inspect_definition_storage

    with transaction.atomic(using="default"):
        with connections["default"].cursor() as cursor:
            cursor.execute("SET LOCAL TRANSACTION READ ONLY")
            cursor.execute("SET LOCAL statement_timeout='20s'")
            cursor.execute("SET LOCAL lock_timeout='3s'")
            configs = list(GroupDBConfig.objects.using("default").select_related("group")
                           .filter(group__code=group_code, db_alias=db_alias))
            if len(configs) != 1 or str(configs[0].group.status).lower() != "active":
                raise RuntimeError("Expected one active tenant configuration")
            config = configs[0]
            central = inspect_definition_storage(cursor)
        transaction.set_rollback(True, using="default")

    conn = _connect_tenant(config)  # Existing Secrets Manager resolver, read-only session.
    try:
        with conn.cursor() as cursor:
            cursor.execute("SET LOCAL statement_timeout='20s'")
            cursor.execute("SET LOCAL lock_timeout='3s'")
            tenant = inspect_definition_storage(cursor)
            if tenant["database"] != config.db_name:
                raise RuntimeError("Tenant database identity mismatch")
            relations = {(row["schema_name"], row["relation_name"]) for row in tenant["relations"]}
            if not {("prj", "projects"), ("gis", "meta_field_def")} <= relations:
                raise RuntimeError("Selected database lacks the required tenant GIS foundation")
    finally:
        conn.rollback()
        conn.close()
    return {"format": "gis-definition-storage-v1",
            "collected_at": datetime.now(timezone.utc).isoformat(),
            "group_code": group_code, "db_alias": db_alias,
            "central": central, "tenant": tenant}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--group-code", required=True)
    parser.add_argument("--db-alias", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    if args.output.exists():
        parser.error("Output exists; choose a new private filename")
    try:
        report = collect(args.group_code, args.db_alias)
        write_private_report(args.output, report)
    except Exception as exc:
        # Database/SDK exceptions may contain connection details. Do not print
        # their text or traceback. A failure produces no successful report.
        print(json.dumps({"ok": False, "error_type": type(exc).__name__}), file=sys.stderr)
        return 2
    print(json.dumps({"ok": True, "scope": "structure_only", "db_writes": 0}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
