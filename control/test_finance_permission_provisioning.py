from io import StringIO
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

from django.core.management.base import CommandError
from django.test import SimpleTestCase, override_settings

from control.management.commands.provision_finance_permissions import Command, _insert_registry_row, requested_role_permissions
from control.models import Permission


class FinancePermissionProvisioningTests(SimpleTestCase):
    def test_editor_mapping_includes_read_without_automatic_role_grants(self):
        self.assertEqual(requested_role_permissions([], []), {"finance.view": set(), "finance.edit": set()})
        self.assertEqual(requested_role_permissions(["viewer"], ["manager"]), {"finance.view": {"viewer", "manager"}, "finance.edit": {"manager"}})

    @override_settings(GF_AUTHZ_CENTRAL_ALIAS="default", CENTRAL_DB_ALIAS="default")
    @patch("control.management.commands.provision_finance_permissions.RolePermission.objects")
    @patch("control.management.commands.provision_finance_permissions.Permission.objects")
    @patch("control.management.commands.provision_finance_permissions.Role.objects")
    def test_plan_performs_no_insert_and_does_not_start_write_transaction(self, roles, permissions, mappings):
        roles.using.return_value.filter.return_value = [SimpleNamespace(code="manager")]
        permissions.using.return_value.filter.return_value = []
        output = StringIO()
        with patch("control.management.commands.provision_finance_permissions.transaction.atomic") as atomic:
            Command(stdout=output).handle(read_role=[], edit_role=["manager"], apply=False)
            atomic.assert_not_called()
        roles.using.return_value.get_or_create.assert_not_called()
        permissions.using.return_value.get_or_create.assert_not_called()
        mappings.using.assert_not_called()
        self.assertIn("no changes made", output.getvalue())

    @override_settings(GF_AUTHZ_CENTRAL_ALIAS="default", CENTRAL_DB_ALIAS="default")
    @patch("control.management.commands.provision_finance_permissions.Role.objects")
    @patch("control.management.commands.provision_finance_permissions.Permission.objects")
    def test_unknown_role_aborts_before_creating_permissions(self, permissions, roles):
        roles.using.return_value.filter.return_value = []
        with self.assertRaises(CommandError):
            Command().handle(read_role=[], edit_role=["unknown"], apply=True)
        permissions.using.assert_not_called()

    @override_settings(GF_AUTHZ_CENTRAL_ALIAS="default", CENTRAL_DB_ALIAS="default")
    @patch("control.management.commands.provision_finance_permissions.transaction.atomic")
    @patch("control.management.commands.provision_finance_permissions.RolePermission.objects")
    @patch("control.management.commands.provision_finance_permissions.Permission.objects")
    @patch("control.management.commands.provision_finance_permissions.Role.objects")
    def test_apply_only_adds_requested_role_pairs_in_one_transaction(self, roles, permissions, mappings, atomic):
        reader, editor = SimpleNamespace(code="reader"), SimpleNamespace(code="editor")
        roles.using.return_value.filter.return_value = [reader, editor]
        permissions.using.return_value.filter.return_value = []
        with patch("control.management.commands.provision_finance_permissions._register_permission", side_effect=lambda alias, code: code), patch("control.management.commands.provision_finance_permissions._register_role_permission") as register:
            Command(stdout=StringIO()).handle(read_role=["reader"], edit_role=["editor"], apply=True)
        atomic.assert_called_once_with(using="default")
        pairs = [(call.args[1].code, call.args[2]) for call in register.call_args_list]
        self.assertCountEqual(pairs, [("reader", "finance.view"), ("editor", "finance.view"), ("editor", "finance.edit")])
        roles.using.return_value.update.assert_not_called()
        mappings.using.return_value.delete.assert_not_called()

    @override_settings(GF_AUTHZ_CENTRAL_ALIAS="tenant-test", CENTRAL_DB_ALIAS="default")
    @patch("control.management.commands.provision_finance_permissions.Role.objects")
    def test_alias_mismatch_fails_before_any_query(self, roles):
        with self.assertRaises(CommandError):
            Command().handle(read_role=[], edit_role=[], apply=True)
        roles.using.assert_not_called()

    def test_unmanaged_permission_name_is_included_without_schema_change(self):
        connection = MagicMock()
        connection.ops.quote_name.side_effect = lambda value: '"' + value + '"'
        connection.introspection.get_table_description.return_value = [
            SimpleNamespace(name=name, null_ok=False, default=None, type_code="text")
            for name in ("id", "code", "name")
        ]
        with patch("control.management.commands.provision_finance_permissions.connections", {"default": connection}):
            _insert_registry_row("default", Permission, {"code": "finance.view"}, {"id": "test-id", "name": "재무 조회"})
        sql, parameters = connection.cursor.return_value.__enter__.return_value.execute.call_args.args
        self.assertIn('"name"', sql)
        self.assertIn("재무 조회", parameters)
        self.assertIn('ON CONFLICT ("code") DO NOTHING', sql)
        self.assertNotIn("ALTER", sql)

    def test_unknown_mandatory_column_aborts_before_insert(self):
        connection = MagicMock()
        connection.introspection.get_table_description.return_value = [SimpleNamespace(name="unknown_required", null_ok=False, default=None, type_code="text")]
        connection.introspection.get_field_type.return_value = "TextField"
        with patch("control.management.commands.provision_finance_permissions.connections", {"default": connection}), self.assertRaises(CommandError):
            _insert_registry_row("default", Permission, {"code": "finance.view"})
        connection.cursor.return_value.__enter__.return_value.execute.assert_not_called()
