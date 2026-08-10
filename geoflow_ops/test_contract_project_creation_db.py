from __future__ import annotations

from unittest.mock import patch

from django.db import IntegrityError, connection
from django.test import TransactionTestCase

from geoflow_ops.models import Contract, Project
from geoflow_ops.services.contract_project_creation import save_new_contract_with_project


class ContractProjectCreationDbTests(TransactionTestCase):
    databases = {"default"}

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        with connection.cursor() as cur:
            cur.execute("CREATE SCHEMA IF NOT EXISTS ctr")
            cur.execute("CREATE SCHEMA IF NOT EXISTS prj")
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS ctr.contracts (
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
                CREATE TABLE IF NOT EXISTS prj.projects (
                    id uuid PRIMARY KEY,
                    contract_id uuid NOT NULL,
                    code text NULL,
                    name text NULL,
                    start_date date NULL,
                    end_date date NULL,
                    status text NULL,
                    description text NULL,
                    org_unit_id uuid NULL,
                    ext jsonb NOT NULL DEFAULT '{}'::jsonb,
                    created_at timestamptz NULL,
                    updated_at timestamptz NULL,
                    CONSTRAINT fk_test_project_contract
                        FOREIGN KEY (contract_id) REFERENCES ctr.contracts(id) ON DELETE CASCADE
                )
                """
            )

    @classmethod
    def tearDownClass(cls):
        with connection.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS prj CASCADE")
            cur.execute("DROP SCHEMA IF EXISTS ctr CASCADE")
        super().tearDownClass()

    def test_contract_and_project_are_created_as_one_pair(self):
        contract = Contract(
            code="26-901",
            name="CI atomic pair",
            status="planned",
            ext=None,
        )

        saved, project = save_new_contract_with_project("default", contract)

        self.assertEqual(Contract.objects.using("default").count(), 1)
        self.assertEqual(Project.objects.using("default").count(), 1)
        self.assertEqual(project.contract_id, saved.id)
        self.assertEqual(project.code, "C26901")
        self.assertEqual(project.name, saved.name)
        self.assertEqual(project.status, "planned")
        self.assertEqual(project.ext, {})
        self.assertIsNotNone(saved.created_at)
        self.assertIsNotNone(project.created_at)

    def test_contract_rolls_back_when_project_creation_fails(self):
        contract = Contract(
            code="26-902",
            name="CI forced rollback",
            status="active",
            ext=None,
        )

        with patch(
            "geoflow_ops.services.contract_project_creation.create_project_for_contract",
            side_effect=IntegrityError("forced project insert failure"),
        ):
            with self.assertRaises(IntegrityError):
                save_new_contract_with_project("default", contract)

        self.assertEqual(Contract.objects.using("default").count(), 0)
        self.assertEqual(Project.objects.using("default").count(), 0)
