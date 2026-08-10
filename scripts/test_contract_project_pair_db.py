from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")
os.environ.setdefault("DJANGO_SECRET_KEY", "contract-project-db-integration")
os.environ.setdefault("CENTRAL_DB_NAME", "postgres")
os.environ.setdefault("CENTRAL_DB_USER", "postgres")
os.environ.setdefault("CENTRAL_DB_PASSWORD", "postgres")
os.environ.setdefault("CENTRAL_DB_HOST", "127.0.0.1")
os.environ.setdefault("CENTRAL_DB_PORT", "5432")
os.environ.setdefault("TENANT_DB_NAME", "postgres")
os.environ.setdefault("TENANT_DB_USER", "postgres")
os.environ.setdefault("TENANT_DB_PASSWORD", "postgres")
os.environ.setdefault("TENANT_DB_HOST", "127.0.0.1")
os.environ.setdefault("TENANT_DB_PORT", "5432")

import django

django.setup()

from django.db import DatabaseError, connections, transaction

from geoflow_ops.models import Contract, Project
from geoflow_ops.services.contract_project_pair import create_project_for_new_contract

ALIAS = "cheonan_db"

# The disposable Actions PostgreSQL service does not require TLS. Override only
# this test connection after Django settings have loaded; production settings are
# not changed.
connections.databases[ALIAS].update(
    {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": "postgres",
        "USER": "postgres",
        "PASSWORD": "postgres",
        "HOST": "127.0.0.1",
        "PORT": "5432",
        "OPTIONS": {},
        "CONN_MAX_AGE": 0,
    }
)
connections[ALIAS].close()

DDL = """
DROP SCHEMA IF EXISTS prj CASCADE;
DROP SCHEMA IF EXISTS ctr CASCADE;
CREATE SCHEMA ctr;
CREATE SCHEMA prj;

CREATE TABLE ctr.contracts (
    id uuid PRIMARY KEY,
    legacy_id bigint NULL,
    code text NULL,
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
);

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
    ext jsonb NULL,
    created_at timestamptz NULL,
    updated_at timestamptz NULL
);
"""

with connections[ALIAS].cursor() as cur:
    cur.execute(DDL)

# Success: one contract and exactly one derived project commit together.
with transaction.atomic(using=ALIAS):
    contract = Contract(code="26-999", name="integration pair", status="active", ext={})
    contract.save(using=ALIAS)
    project = create_project_for_new_contract(ALIAS, contract)
    assert project.contract_id == contract.id
    assert project.code == "C26999"

assert Contract.objects.using(ALIAS).count() == 1
assert Project.objects.using(ALIAS).count() == 1
assert Project.objects.using(ALIAS).filter(contract_id=contract.id).count() == 1

# Invariant: the helper never silently creates a second project for the same
# newly-created contract.
try:
    with transaction.atomic(using=ALIAS):
        create_project_for_new_contract(ALIAS, contract)
except RuntimeError:
    pass
else:
    raise AssertionError("duplicate project invariant was not enforced")
assert Project.objects.using(ALIAS).filter(contract_id=contract.id).count() == 1

# Failure: force the project insert to fail inside the same tenant transaction;
# the contract inserted earlier in that transaction must disappear as well.
with connections[ALIAS].cursor() as cur:
    cur.execute(
        """
        CREATE OR REPLACE FUNCTION prj.fail_atomic_pair_test() RETURNS trigger AS $$
        BEGIN
            IF NEW.code = 'CFAIL' THEN
                RAISE EXCEPTION 'forced disposable project failure';
            END IF;
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        CREATE TRIGGER fail_atomic_pair_test
        BEFORE INSERT ON prj.projects
        FOR EACH ROW EXECUTE FUNCTION prj.fail_atomic_pair_test();
        """
    )

try:
    with transaction.atomic(using=ALIAS):
        failing = Contract(code="FAIL", name="must roll back", status="active", ext={})
        failing.save(using=ALIAS)
        create_project_for_new_contract(ALIAS, failing)
except DatabaseError:
    pass
else:
    raise AssertionError("forced project failure did not abort the transaction")

assert not Contract.objects.using(ALIAS).filter(code="FAIL").exists()
assert not Project.objects.using(ALIAS).filter(code="CFAIL").exists()

print("contract_project_pair_db_success=yes")
print("contract_project_pair_duplicate_guard=yes")
print("contract_project_pair_rollback=yes")
