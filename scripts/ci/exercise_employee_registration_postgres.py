"""Disposable, separate central/tenant PostgreSQL registration regression."""
import importlib
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
if os.environ.get("GITHUB_ACTIONS") != "true" or os.environ.get("CENTRAL_DB_HOST") != "127.0.0.1":
    raise RuntimeError("Disposable CI database required")

import django
import psycopg2
from psycopg2 import sql

django.setup()
from django.db import connections
from django.test import RequestFactory
from control.services import tenant_employee_registration as service
from geoflow_ops import views_employee_profile
from control.services.tenant_role_request_service import TenantRoleRequest, queue_tenant_role_request
from control.services.join_membership_approval_service import JoinMembershipApproval, approve_join_membership

USER, ACTOR, GROUP, ROLE, OTHER_ROLE = (str(UUID(int=i)) for i in range(101, 106))
TENANT_DB = "geoflow_employee_registration_ci"
params = dict(host="127.0.0.1", port=os.environ["CENTRAL_DB_PORT"],
              user=os.environ["CENTRAL_DB_USER"], password=os.environ["CENTRAL_DB_PASSWORD"])


@contextmanager
def tenant_cursor(group_id, *, write=False):
    assert str(group_id) == GROUP, "tenant scope mismatch"
    connection = psycopg2.connect(dbname=TENANT_DB, **params)
    try:
        with connection:
            with connection.cursor() as cursor:
                yield cursor
    finally:
        connection.close()


def central_one(query, params=()):
    with connections["default"].cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchone()


def register(role=ROLE, name=""):
    return service.register_tenant_employee(user_id=USER, group_id=GROUP, role_id=role, actor_user_id=ACTOR, name=name)


def main():
    admin = psycopg2.connect(dbname=os.environ["CENTRAL_DB_NAME"], **params)
    admin.autocommit = True
    with admin.cursor() as cur:
        cur.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(TENANT_DB)))
    admin.close()
    with connections["default"].cursor() as cur:
        cur.execute("ALTER TABLE users ADD COLUMN is_staff boolean NOT NULL DEFAULT false, ADD COLUMN name_display text")
        cur.execute("ALTER TABLE roles ADD COLUMN status text NOT NULL DEFAULT 'active'")
        for uid, email, staff in ((USER, "employee-ci@example.invalid", False), (ACTOR, "admin-ci@example.invalid", True)):
            cur.execute("""INSERT INTO users(id,email,password_hash,is_active,email_verified,is_staff,name_display)
                VALUES (%s,%s,'pbkdf2_sha256$1$salt$hash',true,true,%s,'Joined Employee')""", [uid, email, staff])
        cur.execute("INSERT INTO groups(id,code,status) VALUES (%s,'employee-ci','active')", [GROUP])
        for rid, code in ((ROLE, "project_admin"), (OTHER_ROLE, "viewer")):
            cur.execute("INSERT INTO roles(id,code) VALUES (%s,%s)", [rid, code])
        migration = importlib.import_module("control.migrations.0010_tenant_employee_registrations")
        for operation in migration.Migration.operations:
            cur.execute(operation.sql)
    with tenant_cursor(GROUP, write=True) as cur:
        cur.execute("""CREATE SCHEMA hr;
            CREATE TABLE hr.employee_profile (
                id uuid PRIMARY KEY, central_user_id uuid, email text NOT NULL,
                name text NOT NULL, status text NOT NULL, title text, role_code text,
                is_deleted boolean NOT NULL DEFAULT false,
                created_at timestamptz NOT NULL, updated_at timestamptz NOT NULL
            )""")

    with patch.object(service, "tenant_cursor", tenant_cursor):
        operation = register()
        assert central_one("SELECT status,actor_user_id::text FROM tenant_employee_registrations WHERE id=%s", [operation]) == ("completed", ACTOR)
        register(name="Must Not Overwrite")
        with tenant_cursor(GROUP) as cur:
            cur.execute("SELECT count(*),min(name),min(central_user_id::text) FROM hr.employee_profile")
            assert cur.fetchone() == (1, "Joined Employee", USER)
        assert central_one("SELECT count(*) FROM user_group_map WHERE user_id=%s AND group_id=%s", [USER,GROUP]) == (1,)

        # Existing unlinked employee retains HR attributes when explicitly linked.
        with tenant_cursor(GROUP, write=True) as cur:
            cur.execute("UPDATE hr.employee_profile SET central_user_id=NULL,title='Preserved',status='휴직'")
        register()
        with tenant_cursor(GROUP) as cur:
            cur.execute("SELECT central_user_id::text,title,status FROM hr.employee_profile")
            assert cur.fetchone() == (USER, "Preserved", "휴직")

        # Real central SQL failure occurs AFTER tenant commit. Reconcile by retry.
        with connections["default"].cursor() as cur:
            cur.execute("""CREATE FUNCTION fail_employee_role() RETURNS trigger LANGUAGE plpgsql AS $$
                BEGIN RAISE EXCEPTION 'injected CI failure'; END; $$;
                CREATE TRIGGER fail_employee_role BEFORE UPDATE ON user_group_map
                FOR EACH ROW EXECUTE FUNCTION fail_employee_role()""")
        try:
            register(OTHER_ROLE)
            raise AssertionError("failure unexpectedly succeeded")
        except service.RegistrationRejected as exc:
            assert exc.code == "storage_error"
        assert central_one("SELECT role_id::text FROM user_group_map WHERE user_id=%s", [USER]) == (ROLE,)
        assert central_one("SELECT status FROM tenant_employee_registrations ORDER BY created_at DESC LIMIT 1") == ("failed",)
        with connections["default"].cursor() as cur:
            cur.execute("DROP TRIGGER fail_employee_role ON user_group_map")
        register(OTHER_ROLE)
        assert central_one("SELECT role_id::text FROM user_group_map WHERE user_id=%s", [USER]) == (OTHER_ROLE,)

        # Deleted employee rejects a new role and preserves the existing role.
        with tenant_cursor(GROUP, write=True) as cur:
            cur.execute("UPDATE hr.employee_profile SET is_deleted=true")
        try:
            register()
            raise AssertionError("deleted employee accepted")
        except service.RegistrationRejected as exc:
            assert exc.code == "deleted"
        assert central_one("SELECT role_id::text FROM user_group_map WHERE user_id=%s", [USER]) == (OTHER_ROLE,)
        with tenant_cursor(GROUP, write=True) as cur:
            cur.execute("UPDATE hr.employee_profile SET is_deleted=false")

        # Existing tenant request -> central approval remains usable after transfer.
        with connections["default"].cursor() as cur:
            cur.execute("""ALTER TABLE user_group_map ADD UNIQUE(user_id,group_id);
                CREATE TABLE join_requests (
                    id uuid PRIMARY KEY,user_id uuid,group_id uuid,requested_email text,
                    requested_role_code text,status text,decided_at timestamptz,decided_by uuid,
                    created_at timestamptz,updated_at timestamptz,
                    UNIQUE(user_id,group_id,requested_email))""")
        queue_tenant_role_request(TenantRoleRequest(requester_user_id=ACTOR, group_id=GROUP,
            requested_email="employee-ci@example.invalid", role_code="project_admin"))
        assert central_one("SELECT role_id::text FROM user_group_map WHERE user_id=%s", [USER]) == (OTHER_ROLE,)
        request_id = central_one("SELECT id::text FROM join_requests")[0]
        approve_join_membership(JoinMembershipApproval(request_id=request_id,user_id=USER,
            group_id=GROUP,role_id=ROLE,actor_user_id=ACTOR))
        assert central_one("SELECT role_id::text FROM user_group_map WHERE user_id=%s", [USER]) == (ROLE,)
        with tenant_cursor(GROUP) as cur:
            cur.execute("SELECT count(*),min(title),min(status) FROM hr.employee_profile")
            assert cur.fetchone() == (1, "Preserved", "휴직")

    # A real tenant form cannot pass a stale duplicate check while a central
    # registration is uncommitted. Observe the blocked lock before releasing it.
    alias = "employee_registration_ci"
    config = dict(connections.settings["default"])
    config.update(NAME=TENANT_DB, OPTIONS={"sslmode": "disable", "application_name": "employee_registration_form_ci"})
    connections.settings[alias] = config

    def submit_tenant_form():
        try:
            request = RequestFactory().post("/employees/new/", {"email": "race-ci@example.invalid", "name": "Tenant Form"})
            with patch.object(views_employee_profile, "require_tenant_context", return_value=alias), patch.object(
                views_employee_profile, "employee_access_policy", return_value=SimpleNamespace(can_create=True),
            ):
                return views_employee_profile.employees_create(request).status_code
        finally:
            connections[alias].close()

    with ThreadPoolExecutor(max_workers=1) as pool:
        with tenant_cursor(GROUP, write=True) as cur:
            service.register_employee_profile(cur, user_id=str(UUID(int=999)), email="race-ci@example.invalid", name="Central Form")
            future = pool.submit(submit_tenant_form)
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                blocked = central_one("""SELECT count(*) FROM pg_stat_activity
                    WHERE application_name='employee_registration_form_ci' AND wait_event_type='Lock'""")[0]
                if blocked:
                    break
                if future.done():
                    raise AssertionError("tenant form did not serialize with central registration")
                time.sleep(0.05)
            else:
                raise AssertionError("tenant form lock was not observed")
        assert future.result(timeout=10) == 400
    with tenant_cursor(GROUP) as cur:
        cur.execute("SELECT count(*) FROM hr.employee_profile WHERE email='race-ci@example.invalid'")
        assert cur.fetchone() == (1,)
    print("employee_registration_concurrent_tenant_form=passed")
    print("employee_registration_separate_databases_and_retry=passed")
    print("employee_registration_existing_role_request_approval=passed")


if __name__ == "__main__":
    main()
