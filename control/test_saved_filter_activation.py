from unittest.mock import Mock, patch
from types import SimpleNamespace
import subprocess
from django.test import SimpleTestCase
from django.core.management.base import CommandError
from control.management.commands.activate_saved_filters import forward_plan, TARGET, backup_error_code, backup_tools


class SavedFilterActivationTests(SimpleTestCase):
    def test_already_applied_target_never_rolls_back_descendants(self):
        executor=Mock()
        executor.recorder.applied_migrations.return_value={TARGET,('control','0009_future')}
        self.assertEqual(forward_plan(executor,TARGET),[])
        executor.migration_plan.assert_not_called()

    def test_only_exact_forward_target_is_permitted(self):
        executor=Mock()
        executor.recorder.applied_migrations.return_value=set()
        target=SimpleNamespace(app_label='control',name=TARGET[1])
        executor.migration_plan.return_value=[(target,False)]
        self.assertEqual(forward_plan(executor,TARGET),[(target,False)])
        for plan in [[(target,True)],[(SimpleNamespace(app_label='control',name='0007_admin_visibility'),False)]]:
            executor.migration_plan.return_value=plan
            with self.assertRaises(CommandError):forward_plan(executor,TARGET)


class BackupDiagnosticsTests(SimpleTestCase):
    def test_errors_use_fixed_categories_without_credentials(self):
        for error, expected in [
            (FileNotFoundError('private path'), 'executable_missing'),
            (PermissionError('private path'), 'filesystem_permission_denied'),
            (subprocess.TimeoutExpired('secret command', 1), 'timeout'),
            (subprocess.CalledProcessError(1, 'dump', stderr=b'password authentication failed for private user'), 'authentication_failed'),
            (subprocess.CalledProcessError(1, 'dump', stderr=b'aborting because of server version mismatch'), 'server_version_mismatch'),
        ]:
            self.assertEqual(backup_error_code(error), expected)

    @patch('control.management.commands.activate_saved_filters.Path.glob', return_value=[])
    @patch('control.management.commands.activate_saved_filters.shutil.which', return_value=None)
    def test_missing_client_is_explicit_and_does_not_mutate(self, which, glob):
        connection=Mock(pg_version=160004)
        with self.assertRaisesMessage(CommandError, 'compatible_client_missing_server_major_16'):
            backup_tools(connection)

    @patch('control.management.commands.activate_saved_filters.subprocess.run')
    @patch('control.management.commands.activate_saved_filters.Path.is_file', return_value=True)
    @patch('control.management.commands.activate_saved_filters.Path.glob')
    @patch('control.management.commands.activate_saved_filters.shutil.which', return_value='/usr/bin/pg_dump')
    def test_uses_installed_matching_client_instead_of_old_default(self, which, glob, isfile, run):
        from pathlib import Path
        glob.return_value=[Path('/usr/lib/postgresql/16/bin/pg_dump')]
        run.side_effect=[Mock(stdout=b'pg_dump (PostgreSQL) 14.1'),Mock(stdout=b'pg_dump (PostgreSQL) 16.4')]
        dump,restore=backup_tools(Mock(pg_version=160004))
        self.assertEqual(dump,'/usr/lib/postgresql/16/bin/pg_dump')
        self.assertEqual(restore,'/usr/lib/postgresql/16/bin/pg_restore')
