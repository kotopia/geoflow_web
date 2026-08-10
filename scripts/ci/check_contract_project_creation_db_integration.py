from __future__ import annotations

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.ci_migration_settings")

import django

django.setup()

from django.db import IntegrityError, connections

from geoflow_ops.models import Contract, Project
from geoflow_ops.services import contract_project_creation as service


ALIAS = "default"


def bootstrap() -> None:
    with connections[ALIAS].cursor() as cur:
        cur.execute("DROP SCHEMA IF EXISTS prj CASCADE")
        cur.execute("DROP SCHEMA IF EXISTS ctr CASCADE")
        cur.execute("CREATE SCHEMA ctr")
        cur.execute("CREATE SCHEMA prj")
        cur.execute(
            """
            CREATE TABLE ctr.contracts (
                id uuid PRIMARY KEY,
                legacy_id bigint NULL,
                code text NULL UNIQUE,
                name text NOT NULL,
                start_date date NULL,
                end_date date NULL,
                amount numeric(14,0) NULL,
                status text NULL,
                kind text NULL,
                division text NULL,
                client_id uuid NULL,
                sub_client_id uuid NULL,
                org_unit_id uuid NULL,
                ext jsonb NULL,
                created_at timestamptz NULL,
                updated_at timestamptz NULL,
                description text NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE prj.projects (
                id uuid PRIMARY KEY,
                contract_id uuid NOT NULL REFERENCES ctr.contracts(id) ON DELETE CASCADE,
                code text NULL,
                name text NULL,
                start_date date NULL,
                end_date date NULL,
                status text NULL,
                description text NULL,
                org_unit_id uuid NULL,
                ext jsonb NOT NULL DEFAULT '{}'::jsonb,
                created_at timestamptz NULL,
                updated_at timestamptz NULL
            )
            """
        )


def scalar(sql: str) -> int:
    with connections[ALIAS].cursor() as cur:
        cur.execute(sql)
        return int(cur.fetchone()[0])


def successful_pair() -> None:
    contract = Contract(code="26-971", name="ci-pair", status="planned", ext=None)
    saved, project = service.save_new_contract_with_project(ALIAS, contract)
    assert scalar("SELECT COUNT(*) FROM ctr.contracts") == 1
    assert scalar("SELECT COUNT(*) FROM prj.projects") == 1
    assert project.contract_id == saved.id
    assert project.code == "C26971"
    assert project.status == "planned"
    assert project.ext == {}


def rollback_on_project_failure() -> None:
    original = service.create_project_for_contract

    def fail_project(*args, **kwargs):
        raise IntegrityError("forced project failure")

    service.create_project_for_contract = fail_project
    try:
        contract = Contract(code="26-972", name="ci-rollback", status="active", ext=None)
        try:
            service.save_new_contract_with_project(ALIAS, contract)
        except IntegrityError:
            pass
        else:
            raise AssertionError("forced project failure did not propagate")
    finally:
        service.create_project_for_contract = original

    assert scalar("SELECT COUNT(*) FROM ctr.contracts WHERE code = '26-972'") == 0
    assert scalar("SELECT COUNT(*) FROM prj.projects WHERE code = 'C26972'") == 0


def main() -> None:
    bootstrap()
    successful_pair()
    rollback_on_project_failure()
    print("contract_project_db_integration=success")


if __name__ == "__main__":
    main()
