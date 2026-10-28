from types import SimpleNamespace
from unittest import TestCase
from unittest.mock import Mock, patch
from django.core.management.base import CommandError
from control.management.commands.activate_company_overview import forward_plan, TARGET, DEPENDENCY, choose_eligible


class CompanyActivationTests(TestCase):
    def executor(self, applied, plan):
        executor=Mock()
        executor.recorder.applied_migrations.return_value=applied
        executor.migration_plan.return_value=plan
        return executor

    def test_applied_target_never_unapplies_descendants(self):
        executor=self.executor({TARGET,DEPENDENCY},[(SimpleNamespace(app_label='webgisapp',name='0050_other'),True)])
        self.assertEqual(forward_plan(executor),[])
        executor.migration_plan.assert_not_called()

    def test_missing_dependency_blocks(self):
        with self.assertRaises(CommandError): forward_plan(self.executor(set(),[]))

    def test_unrelated_or_backward_migration_blocks(self):
        for plan in [[(SimpleNamespace(app_label='webgisapp',name='0048_gis_project_reference_groups'),False)],[(SimpleNamespace(app_label=TARGET[0],name=TARGET[1]),True)]]:
            with self.assertRaises(CommandError): forward_plan(self.executor({DEPENDENCY},plan))

    def test_exact_additive_plan_allowed(self):
        plan=[(SimpleNamespace(app_label=TARGET[0],name=TARGET[1]),False)]
        self.assertEqual(forward_plan(self.executor({DEPENDENCY},plan)),plan)

    def test_only_one_eligible_target_may_be_selected(self):
        for targets in [[],[Mock(),Mock()]]:
            with self.assertRaises(CommandError): choose_eligible(targets)
        target = Mock()
        self.assertIs(choose_eligible([target]),target)

    def test_activation_allowlist_does_not_enable_other_tenants(self):
        from django.test import override_settings
        from geoflow_ops.services.company_overview import enabled
        with override_settings(GEOFLOW_COMPANY_OVERVIEW_ENABLED=True, GEOFLOW_COMPANY_OVERVIEW_TENANTS=('ready',)):
            self.assertTrue(enabled('ready'))
            self.assertFalse(enabled('unprepared'))
            self.assertFalse(enabled('default'))
