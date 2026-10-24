from unittest.mock import Mock
from types import SimpleNamespace
from django.test import SimpleTestCase
from django.core.management.base import CommandError
from control.management.commands.activate_saved_filters import forward_plan, TARGET


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
