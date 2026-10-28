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


class CompanyActivationDiagnosticsTests(TestCase):
    def test_safe_categories_never_expose_private_error_messages(self):
        from django.db import OperationalError
        from django.db.migrations.exceptions import InconsistentMigrationHistory
        from control.services.tenant_db_secret_resolver import TenantDBCredentialError
        from control.management.commands.activate_company_overview import activation_stage
        for kind, category in [(OperationalError, 'database'),
                               (InconsistentMigrationHistory, 'inconsistent_history'),
                               (TenantDBCredentialError, 'credential_resolution'),
                               (KeyError, 'configuration_key'), (AttributeError, 'attribute'),
                               (RuntimeError, 'unexpected')]:
            with self.assertRaises(CommandError) as caught:
                with activation_stage('tenant_readiness'):
                    raise kind('private credential host and tenant identifier')
            self.assertEqual(str(caught.exception),
                             'company_activation_stage=tenant_readiness category='+category)

    def test_existing_guard_remains_fatal(self):
        from control.management.commands.activate_company_overview import activation_stage
        error = CommandError('company_unexpected_migration_plan')
        with self.assertRaises(CommandError) as caught:
            with activation_stage('migration_plan'):
                raise error
        self.assertIs(caught.exception, error)


class EmptyMergeHistoryTests(TestCase):
    def executor(self, *, extra_gap=False, parents_present=True, operations=None):
        from control.management.commands.activate_company_overview import EMPTY_MERGE, MERGE_CHILD, MERGE_PARENTS
        from django.db.migrations.exceptions import InconsistentMigrationHistory
        executor = Mock()
        applied = set(MERGE_PARENTS) | {MERGE_CHILD, DEPENDENCY}
        if not parents_present:
            applied.remove(next(iter(MERGE_PARENTS)))
        nodes = {key: SimpleNamespace(parents=[]) for key in applied | MERGE_PARENTS}
        nodes[EMPTY_MERGE] = SimpleNamespace(parents=[SimpleNamespace(key=p) for p in MERGE_PARENTS])
        nodes[MERGE_CHILD] = SimpleNamespace(parents=[SimpleNamespace(key=EMPTY_MERGE)])
        if extra_gap:
            nodes[DEPENDENCY].parents = [SimpleNamespace(key=('webgisapp','0047_missing'))]
        executor.loader.graph = SimpleNamespace(node_map=nodes)
        executor.loader.replacements = {}
        executor.loader.disk_migrations = {EMPTY_MERGE:SimpleNamespace(operations=operations or [],dependencies=list(MERGE_PARENTS))}
        executor.loader.check_consistent_history.side_effect=InconsistentMigrationHistory('private alias')
        executor.recorder.applied_migrations.return_value=applied
        return executor

    def test_exact_audited_gap_is_readonly(self):
        from control.management.commands.activate_company_overview import history_repair_needed
        executor=self.executor()
        self.assertTrue(history_repair_needed(executor, Mock()))
        executor.recorder.record_applied.assert_not_called()

    def test_other_gap_missing_parent_or_nonempty_merge_is_rejected(self):
        from control.management.commands.activate_company_overview import history_repair_needed
        for executor in [self.executor(extra_gap=True),self.executor(parents_present=False),self.executor(operations=[Mock()])]:
            with self.assertRaises(CommandError): history_repair_needed(executor,Mock())
            executor.recorder.record_applied.assert_not_called()

    def test_no_implicit_approval(self):
        from control.management.commands.activate_company_overview import reconcile_empty_merge
        executor=self.executor()
        with self.assertRaises(CommandError):
            reconcile_empty_merge(executor,Mock(),approved=False)
        executor.recorder.record_applied.assert_not_called()

    def test_consistent_history_needs_no_repair(self):
        from control.management.commands.activate_company_overview import reconcile_empty_merge
        executor=self.executor()
        executor.loader.check_consistent_history.side_effect=None
        reconcile_empty_merge(executor,Mock(),approved=True)
        executor.recorder.record_applied.assert_not_called()


from unittest import skipUnless
from django.db import connections

@skipUnless(connections['company_test'].vendor == 'postgresql', 'Disposable PostgreSQL CI only')
class EmptyMergePostgresTests(TestCase):
    def test_real_history_repair_is_exact_idempotent_and_transactional(self):
        from django.db import transaction
        from django.db.migrations.executor import MigrationExecutor
        from django.db.migrations.recorder import MigrationRecorder
        from django.db.migrations.exceptions import InconsistentMigrationHistory
        from control.management.commands.activate_company_overview import EMPTY_MERGE, reconcile_empty_merge
        connection=connections['company_test']
        recorder=MigrationRecorder(connection)
        recorder.ensure_schema()
        # Synthetic history only; never used outside the isolated localhost CI DB.
        with transaction.atomic(using='company_test'):
            executor=MigrationExecutor(connection)
            for key in executor.loader.graph.node_map:
                if key not in (EMPTY_MERGE,TARGET):
                    recorder.record_applied(*key)
            executor=MigrationExecutor(connection)
            with self.assertRaises(InconsistentMigrationHistory):
                executor.loader.check_consistent_history(connection)
            with self.assertRaises(CommandError):
                reconcile_empty_merge(executor,connection,approved=False)
            self.assertEqual([(m.app_label,m.name) for m, backwards in forward_plan(executor, allow_empty_merge=True)], [EMPTY_MERGE,TARGET])
            before=set(recorder.applied_migrations())
            with self.assertRaises(RuntimeError):
                with transaction.atomic(using='company_test'):
                    reconcile_empty_merge(executor,connection,approved=True)
                    self.assertEqual(set(recorder.applied_migrations())-before,{EMPTY_MERGE})
                    raise RuntimeError('simulate subsequent migration failure')
            self.assertEqual(set(recorder.applied_migrations()),before)
            reconcile_empty_merge(executor,connection,approved=True)
            self.assertEqual([(m.app_label,m.name) for m, backwards in forward_plan(MigrationExecutor(connection))], [TARGET])
            reconcile_empty_merge(MigrationExecutor(connection),connection,approved=True)
            self.assertEqual(set(recorder.applied_migrations())-before,{EMPTY_MERGE})
            self.assertEqual(recorder.migration_qs.filter(app=EMPTY_MERGE[0],name=EMPTY_MERGE[1]).count(),1)
            transaction.set_rollback(True,using='company_test')
