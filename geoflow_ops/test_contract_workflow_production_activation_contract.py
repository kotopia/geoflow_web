from pathlib import Path

from django.test import SimpleTestCase


ROOT = Path(__file__).resolve().parents[1]
ACTIVATION = ROOT / ".github" / "workflows" / "phase4-contract-workflow-production-activation.yml"
WORKBOARD_DEPLOY = ROOT / ".github" / "workflows" / "phase4-workboard-production-deploy.yml"
HANDOFF_ACTIVATION = ROOT / ".github" / "workflows" / "phase4-workflow-handoff-production-activation.yml"
MYINFO_ACTIVATION = ROOT / ".github" / "workflows" / "phase4-myinfo-hr-masters-production-activation.yml"
MIGRATION = ROOT / "geoflow_ops" / "migrations" / "0026_contract_completion_event_backfill.py"


class ContractWorkflowProductionActivationContractTests(SimpleTestCase):
    def test_activation_is_protected_exact_release_and_stabilized_only(self):
        source = ACTIVATION.read_text(encoding="utf-8")
        lowered = source.lower()
        self.assertIn("environment: production", source)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', source)
        self.assertIn("candidate_sha_not_current_release_head", source)
        self.assertIn("service='geoflow-stabilized.service'", source)
        self.assertNotIn("iroomsng", lowered)
        self.assertNotIn("nginx", lowered)
        self.assertIn("https://geoflow.co.kr/login/", source)

    def _assert_deferred_for_0026(self, path: Path, classifier: str, output_expr: str):
        source = path.read_text(encoding="utf-8")
        self.assertIn(classifier, source)
        self.assertIn("0026_contract_completion_event_backfill.py", source)
        self.assertIn("requires_contract_workflow_activation", source)
        self.assertIn(output_expr, source)
        self.assertLess(source.index(classifier), source.index("environment: production"))

    def test_other_overlapping_production_paths_defer_to_contract_activation(self):
        self._assert_deferred_for_0026(
            WORKBOARD_DEPLOY,
            "classify-workboard-deploy",
            "needs.classify-workboard-deploy.outputs.requires_contract_activation != 'true'",
        )
        self._assert_deferred_for_0026(
            HANDOFF_ACTIVATION,
            "classify-workflow-handoff-activation",
            "needs.classify-workflow-handoff-activation.outputs.requires_contract_workflow_activation != 'true'",
        )
        self._assert_deferred_for_0026(
            MYINFO_ACTIVATION,
            "classify-myinfo-hr-activation",
            "needs.classify-myinfo-hr-activation.outputs.requires_contract_workflow_activation != 'true'",
        )

    def test_activation_prechecks_all_active_tenants_before_writes(self):
        source = ACTIVATION.read_text(encoding="utf-8")
        self.assertIn("contract_workflow_activation_all_tenants_prechecked=yes", source)
        self.assertIn('DEPENDENCY = "0025_myinfo_hr_masters"', source)
        self.assertIn("0025_dependency_not_applied", source)
        self.assertIn('BUSINESS_RELATIONS = {', source)
        self.assertIn('"ctr.contracts"', source)
        self.assertIn('"ops.process_events"', source)
        self.assertIn('relation_exists(cur, "django_migrations")', source)
        self.assertIn("schema_absent_skipped", source)
        self.assertIn("partial_schema", source)

    def test_activation_verifies_exact_expected_data_delta(self):
        source = ACTIVATION.read_text(encoding="utf-8")
        for token in (
            "existing event content changed",
            "contract content other than status/updated_at changed",
            "non-completed contract status changed",
            "migrated completed contract missing completion event",
            "unexpected migrated event content",
            "legacy completed contract status remains",
            "completion event delta unexpected",
            "contract_workflow_activation_db_complete=yes",
        ):
            self.assertIn(token, source)
        self.assertIn("legacy_contract_status_migration", source)
        self.assertIn("system:migration:0026", source)

    def test_candidate_code_is_checked_before_business_data_change(self):
        source = ACTIVATION.read_text(encoding="utf-8")
        self.assertIn("contract_workflow_activation_candidate_check=yes", source)
        self.assertIn("worktree add --detach", source)
        self.assertLess(
            source.index("contract_workflow_activation_candidate_check=yes"),
            source.index("Phase 1: fail closed before any tenant write"),
        )

    def test_migration_is_narrow_idempotent_completion_conversion(self):
        source = MIGRATION.read_text(encoding="utf-8")
        lowered = source.lower()
        self.assertIn("legacy_contract_status_migration", source)
        self.assertIn("'closeout_complete'", source)
        self.assertIn("NOT EXISTS", source)
        self.assertIn("SET status = NULL", source)
        self.assertIn("occurred_at_inferred", source)
        for forbidden in (
            "delete from ctr.contracts",
            "truncate ctr.contracts",
            "drop table ctr.contracts",
            "delete from ops.process_events",
            "truncate ops.process_events",
            "drop table ops.process_events",
        ):
            self.assertNotIn(forbidden, lowered)

    def test_activation_deploys_code_only_after_db_completion(self):
        source = ACTIVATION.read_text(encoding="utf-8")
        self.assertLess(
            source.index("contract_workflow_activation_db_complete=yes"),
            source.index('git -C "$repo" checkout -B "$expected_branch" "$candidate_sha"'),
        )
        self.assertIn("contract_workflow_activation_public_login_status", source)
        self.assertIn("contract_workflow_production_activation_complete=yes", source)
