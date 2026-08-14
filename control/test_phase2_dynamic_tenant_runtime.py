import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

from django.test import SimpleTestCase, override_settings

from control.views_auth import _candidate_is_selectable, _configured_static_tenant_aliases


ROOT = Path(__file__).resolve().parents[1]


class Phase2DynamicTenantRuntimeTests(SimpleTestCase):
    def test_secret_reference_mode_omits_static_default_tenant_alias(self):
        environ = os.environ.copy()
        environ.update(
            {
                "DJANGO_SECRET_KEY": "ci-phase2-dynamic-tenant-runtime-key-0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZ",
                "TENANT_DB_REQUIRE_SECRET_REFERENCES": "1",
            }
        )
        code = """
from geoflow_project import settings as runtime_settings
assert runtime_settings.TENANT_DB_REQUIRE_SECRET_REFERENCES is True
assert runtime_settings.STATIC_TENANT_DB_ALIASES == ()
assert runtime_settings.DEFAULT_TENANT_DB_ALIAS not in runtime_settings.DATABASES
"""
        result = subprocess.run(
            [sys.executable, "-c", code],
            cwd=ROOT,
            env=environ,
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    @override_settings(
        CENTRAL_DB_ALIAS="default",
        DEFAULT_TENANT_DB_ALIAS="cheonan_db",
        STATIC_TENANT_DB_ALIASES=(),
        DATABASES={"default": {"ENGINE": "django.db.backends.postgresql"}},
    )
    def test_default_tenant_alias_uses_complete_central_config_when_static_trust_is_off(self):
        config = SimpleNamespace(
            db_alias="cheonan_db",
            db_name="tenant-db",
            db_host="tenant.example.internal",
            db_port=5432,
            db_user="tenant-user",
            db_password="aws-secretsmanager:tenant-secret-ref",
        )
        group = SimpleNamespace(status="active", groupdbconfig=config)
        membership = SimpleNamespace(
            group_id="group-id",
            status="active",
            group=group,
        )
        candidate = {
            "id": "group-id",
            "code": "tenant-code",
            "name": "Tenant",
            "db_alias": "cheonan_db",
        }

        self.assertEqual(_configured_static_tenant_aliases(), set())
        self.assertTrue(_candidate_is_selectable(candidate, membership))
