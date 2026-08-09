from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import SimpleTestCase


class TenantDBSecretRefAuditTests(SimpleTestCase):
    def _run(self, rows, *, strict=True):
        manager = MagicMock()
        manager.using.return_value.select_related.return_value.order_by.return_value = rows
        stdout = StringIO()
        with patch(
            "control.management.commands.check_tenant_db_secret_refs.GroupDBConfig.objects",
            manager,
        ):
            args = ["check_tenant_db_secret_refs"]
            if strict:
                args.append("--strict")
            call_command(*args, stdout=stdout)
        return stdout.getvalue()

    @staticmethod
    def _row(status, password):
        return SimpleNamespace(
            group=SimpleNamespace(status=status),
            db_password=password,
        )

    def test_strict_allows_empty_password_for_inactive_tenant(self):
        output = self._run(
            [
                self._row(
                    "active",
                    "aws-secretsmanager:geoflow/tenant-db/example/password#password",
                ),
                self._row("inactive", ""),
            ]
        )
        self.assertIn("tenant_db_secret_ref_active_empty=0", output)
        self.assertIn("tenant_db_secret_ref_inactive_empty=1", output)
        self.assertIn("tenant_db_secret_refs_ready=yes", output)

    def test_strict_rejects_empty_password_for_active_tenant(self):
        with self.assertRaises(CommandError):
            self._run([self._row("active", "")])

    def test_strict_rejects_plaintext_even_for_inactive_tenant(self):
        with self.assertRaises(CommandError):
            self._run([self._row("inactive", "legacy-password")])

    def test_strict_rejects_plaintext_for_active_tenant(self):
        with self.assertRaises(CommandError):
            self._run([self._row("active", "legacy-password")])
