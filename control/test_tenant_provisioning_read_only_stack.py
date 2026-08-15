import uuid

from botocore.exceptions import ClientError
from django.test import SimpleTestCase

from control.services.tenant_provisioning_backend_readiness import (
    inspect_tenant_provisioning_backend_readiness,
    readiness_matches_plan,
)
from control.services.tenant_provisioning_contract import (
    TenantProvisioningSnapshot,
    build_tenant_provisioning_plan,
)
from control.services.tenant_provisioning_read_only_stack import (
    build_production_shape_read_only_tenant_provisioning_probe,
)


class FakePostgresCursor:
    ALLOWED_STATEMENTS = {
        "SHOW transaction_read_only",
        "SELECT 1 FROM pg_database WHERE datname=%s LIMIT 1",
        "SELECT 1 FROM pg_roles WHERE rolname=%s LIMIT 1",
    }

    def __init__(self, ledger):
        self.ledger = ledger
        self.last_statement = None

    def execute(self, statement, params=None):
        if statement not in self.ALLOWED_STATEMENTS:
            raise AssertionError(f"unexpected_postgres_statement:{statement}")
        self.last_statement = statement
        self.ledger.append(("postgres_execute", statement, tuple(params or ())))

    def fetchone(self):
        if self.last_statement == "SHOW transaction_read_only":
            return ("on",)
        return None

    def close(self):
        self.ledger.append(("postgres_cursor_close",))


class FakePostgresConnection:
    def __init__(self, ledger):
        self.ledger = ledger

    def cursor(self):
        self.ledger.append(("postgres_cursor",))
        return FakePostgresCursor(self.ledger)

    def close(self):
        self.ledger.append(("postgres_connection_close",))


class FakePostgresConnector:
    read_only = True

    def __init__(self, ledger):
        self.ledger = ledger

    def __call__(self, *, host, port):
        self.ledger.append(("postgres_connect", host, port))
        return FakePostgresConnection(self.ledger)


class FakeSecretsManagerClient:
    def __init__(self, ledger, *, failure_code="ResourceNotFoundException"):
        self.ledger = ledger
        self.failure_code = failure_code

    def describe_secret(self, *, SecretId):
        self.ledger.append(("describe_secret", SecretId))
        raise ClientError(
            {"Error": {"Code": self.failure_code, "Message": "provider detail private"}},
            "DescribeSecret",
        )


class FakeRuntimeSecretScope:
    read_only = True

    def __init__(self, ledger, *, ready=True):
        self.ledger = ledger
        self.ready = ready

    def exact_secret_read_ready(self, *, secret_id):
        self.ledger.append(("runtime_scope", secret_id))
        return self.ready


class FakePublicationQuerySet:
    def __init__(self, ledger):
        self.ledger = ledger

    def filter(self, *args, **kwargs):
        self.ledger.append(("publication_filter", len(args), tuple(sorted(kwargs))))
        return self

    def exclude(self, *args, **kwargs):
        self.ledger.append(("publication_exclude", len(args), tuple(sorted(kwargs))))
        return self

    def exists(self):
        self.ledger.append(("publication_exists",))
        return False

    def create(self, *args, **kwargs):
        raise AssertionError("publication_create_forbidden")

    def update(self, *args, **kwargs):
        raise AssertionError("publication_update_forbidden")

    def delete(self, *args, **kwargs):
        raise AssertionError("publication_delete_forbidden")


class FakePublicationManager:
    def __init__(self, ledger):
        self.ledger = ledger

    def using(self, alias):
        self.ledger.append(("publication_using", alias))
        return FakePublicationQuerySet(self.ledger)

    def create(self, *args, **kwargs):
        raise AssertionError("publication_manager_create_forbidden")

    def update(self, *args, **kwargs):
        raise AssertionError("publication_manager_update_forbidden")

    def delete(self, *args, **kwargs):
        raise AssertionError("publication_manager_delete_forbidden")


class ReadOnlyProbeStackTests(SimpleTestCase):
    def setUp(self):
        self.ledger = []
        self.group_id = str(uuid.uuid4())
        snapshot = TenantProvisioningSnapshot(
            group_id=self.group_id,
            group_code="read-only-stack-city",
            group_status="active",
            existing_config_present=False,
            identifier_conflict=False,
        )
        self.plan = build_tenant_provisioning_plan(
            snapshot,
            db_host="db.internal.example",
            db_port="5432",
            provisioning_enabled=True,
            provisioner_ready=True,
            secret_reference_runtime_required=True,
        )

    def _publication_model(self):
        return type(
            "FakePublicationModel",
            (),
            {"objects": FakePublicationManager(self.ledger)},
        )

    def _build_probe(self, *, secret_failure="ResourceNotFoundException", runtime_scope=None):
        return build_production_shape_read_only_tenant_provisioning_probe(
            postgres_connector=FakePostgresConnector(self.ledger),
            secrets_manager_client=FakeSecretsManagerClient(
                self.ledger,
                failure_code=secret_failure,
            ),
            runtime_secret_scope=runtime_scope or FakeRuntimeSecretScope(self.ledger),
            central_database_alias="central",
            publication_model=self._publication_model(),
        )

    def test_real_shaped_readers_compose_without_enabling_execution(self):
        probe = self._build_probe()

        readiness = inspect_tenant_provisioning_backend_readiness(self.plan, probe)

        self.assertTrue(probe.read_only)
        self.assertTrue(readiness.ready)
        self.assertFalse(readiness.execution_available)
        self.assertFalse(self.plan.execution_available)
        self.assertTrue(readiness_matches_plan(readiness, self.plan))

        statements = [entry[1] for entry in self.ledger if entry[0] == "postgres_execute"]
        self.assertEqual(
            statements,
            [
                "SHOW transaction_read_only",
                "SELECT 1 FROM pg_database WHERE datname=%s LIMIT 1",
                "SHOW transaction_read_only",
                "SELECT 1 FROM pg_roles WHERE rolname=%s LIMIT 1",
            ],
        )
        self.assertEqual(
            [entry[0] for entry in self.ledger].count("describe_secret"),
            1,
        )
        self.assertEqual(
            [entry[0] for entry in self.ledger].count("runtime_scope"),
            1,
        )
        self.assertEqual(
            [entry[0] for entry in self.ledger].count("publication_exists"),
            2,
        )

    def test_non_read_only_runtime_scope_is_rejected_before_any_metadata_read(self):
        scope = FakeRuntimeSecretScope(self.ledger)
        scope.read_only = False

        with self.assertRaisesRegex(RuntimeError, "read_only_dependency_required"):
            self._build_probe(runtime_scope=scope)

        self.assertEqual(self.ledger, [])

    def test_missing_central_alias_is_rejected_before_any_metadata_read(self):
        with self.assertRaisesRegex(ValueError, "central_database_alias_required"):
            build_production_shape_read_only_tenant_provisioning_probe(
                postgres_connector=FakePostgresConnector(self.ledger),
                secrets_manager_client=FakeSecretsManagerClient(self.ledger),
                runtime_secret_scope=FakeRuntimeSecretScope(self.ledger),
                central_database_alias="",
                publication_model=self._publication_model(),
            )

        self.assertEqual(self.ledger, [])

    def test_ambiguous_secret_provider_failure_fails_closed_without_leaking_detail(self):
        probe = self._build_probe(secret_failure="AccessDeniedException")

        readiness = inspect_tenant_provisioning_backend_readiness(self.plan, probe)

        checks = {check.code: check.ready for check in readiness.checks}
        self.assertFalse(readiness.ready)
        self.assertFalse(checks["secret_target_safe"])
        rendered = repr(readiness)
        self.assertNotIn("provider detail private", rendered)
        self.assertNotIn(self.group_id, rendered)
        self.assertNotIn(self.plan.secret_id, rendered)
        self.assertNotIn(self.plan.db_host, rendered)
