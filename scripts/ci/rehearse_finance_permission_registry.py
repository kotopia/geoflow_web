"""Verify unmanaged central registry compatibility in disposable CI Postgres."""
import os
import sys
from io import StringIO
from pathlib import Path
from uuid import uuid4

if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("CENTRAL_DB_HOST") not in {"127.0.0.1", "localhost"}:
    raise RuntimeError("Finance registry rehearsal is restricted to local disposable GitHub CI databases")
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["DJANGO_SETTINGS_MODULE"] = "geoflow_project.ci_migration_settings"

import django
django.setup()

from django.core.management import call_command
from django.db import connection, transaction
from control.models import Permission, Role, RolePermission

with transaction.atomic():
    with connection.cursor() as cursor:
        cursor.execute("CREATE SCHEMA finance_permission_rehearsal")
        cursor.execute("SET LOCAL search_path TO finance_permission_rehearsal")
        cursor.execute("CREATE TABLE roles (id uuid PRIMARY KEY, code text NOT NULL UNIQUE, name text NOT NULL)")
        cursor.execute("CREATE TABLE permissions (id uuid PRIMARY KEY, code text NOT NULL UNIQUE, name text NOT NULL)")
        # The unmanaged RolePermission model assumes a generated numeric id;
        # some central installations instead require a UUID with no default.
        cursor.execute("CREATE TABLE role_permissions (id uuid PRIMARY KEY, role_id uuid NOT NULL REFERENCES roles(id), permission_id uuid NOT NULL REFERENCES permissions(id), UNIQUE(role_id, permission_id))")
    for code in ("manager", "tenant_admin"):
        Role.objects.create(id=uuid4(), code=code, name=code)
    arguments = ("--edit-role", "manager", "--edit-role", "tenant_admin")
    call_command("provision_finance_permissions", *arguments, stdout=StringIO())
    assert Permission.objects.count() == 0 and RolePermission.objects.count() == 0
    for _ in range(2):
        call_command("provision_finance_permissions", *arguments, "--apply", stdout=StringIO())
        assert Permission.objects.count() == 2 and RolePermission.objects.count() == 4
    with connection.cursor() as cursor:
        cursor.execute("SELECT name FROM permissions")
        assert all(row[0] for row in cursor.fetchall())
    # Roll back the entire schema and its synthetic rows, including on success.
    transaction.set_rollback(True)
print("finance_permission_postgres_registry_rehearsal=yes")
