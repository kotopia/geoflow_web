from io import StringIO
from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from django.core.management.base import CommandError
from control.management.commands import activate_company_workspace as rollout


class WorkspaceActivationTests(TestCase):
    def executor(self, applied, plan):
        executor = Mock()
        executor.recorder.applied_migrations.return_value = applied
        executor.migration_plan.return_value = plan
        return executor

    def test_requires_dependency_and_exact_forward_plan(self):
        step = SimpleNamespace(app_label=rollout.TARGET[0], name=rollout.TARGET[1])
        valid = [(step, False)]
        self.assertEqual(rollout.forward_plan(self.executor({rollout.DEPENDENCY}, valid)), valid)
        for applied, plan in [(set(), valid), ({rollout.DEPENDENCY}, []),
                              ({rollout.DEPENDENCY}, [(step, True)]),
                              ({rollout.DEPENDENCY}, valid * 2)]:
            with self.assertRaises(CommandError):
                rollout.forward_plan(self.executor(applied, plan))

    def test_applied_target_never_rolls_back_descendants(self):
        executor = self.executor({rollout.DEPENDENCY, rollout.TARGET}, [Mock()])
        self.assertEqual(rollout.forward_plan(executor), [])
        executor.migration_plan.assert_not_called()

    def execute(self, *, apply=False, backup_dir=None, enabled=True, backup_error=None):
        connection = Mock(vendor='postgresql', alias='company_test')
        step = SimpleNamespace(app_label=rollout.TARGET[0], name=rollout.TARGET[1])
        executor = self.executor({rollout.DEPENDENCY}, [(step, False)])
        with patch.object(rollout, 'tenant_connection', return_value=connection), \
             patch.object(rollout, 'enabled', return_value=enabled), \
             patch.object(rollout, 'MigrationExecutor', return_value=executor), \
             patch.object(rollout, 'backup_central', side_effect=backup_error) as backup:
            try:
                rollout.Command(stdout=StringIO()).handle(apply=apply, verify=False, backup_dir=backup_dir)
            finally:
                executor.migrate.assert_not_called()
                connection.cursor.assert_not_called()
            return backup

    def test_default_is_readonly(self):
        self.execute().assert_not_called()

    def test_disabled_tenant_is_rejected(self):
        with self.assertRaisesRegex(CommandError, 'enabled_postgres_tenant'):
            self.execute(enabled=False, apply=True)

    def test_backup_required_before_mutation(self):
        with self.assertRaisesRegex(CommandError, 'private_backup_required'):
            self.execute(apply=True)

    def test_failed_backup_prevents_mutation_and_hides_private_details(self):
        with self.assertRaises(CommandError) as caught:
            self.execute(apply=True, backup_dir='/synthetic', backup_error=RuntimeError('private-password'))
        self.assertNotIn('private-password', str(caught.exception))
