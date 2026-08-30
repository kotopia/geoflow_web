from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "phase4-employee-soft-delete-production-activation.yml"
WORKBOARD_DEPLOY = ROOT / ".github" / "workflows" / "phase4-workboard-production-deploy.yml"
MYINFO_ACTIVATION = ROOT / ".github" / "workflows" / "phase4-myinfo-hr-masters-production-activation.yml"


class EmployeeSoftDeleteProductionActivationContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = WORKFLOW.read_text(encoding="utf-8")
        cls.lowered = cls.source.lower()
        cls.workboard = WORKBOARD_DEPLOY.read_text(encoding="utf-8")
        cls.myinfo = MYINFO_ACTIVATION.read_text(encoding="utf-8")

    def test_release_push_trigger_is_narrow_and_production_protected(self):
        self.assertIn("release/stabilized-deploy", self.source)
        self.assertIn("geoflow_ops/migrations/0027_employee_profile_soft_delete.py", self.source)
        self.assertIn("environment: production", self.source)
        self.assertIn('test "$(git rev-parse HEAD)" = "$GITHUB_SHA"', self.source)
        self.assertIn("employee_soft_delete_activation_blocker=release_advanced", self.source)
        self.assertIn("candidate_sha_not_current_release_head", self.source)

    def test_clean_stabilized_host_and_secret_reference_inventory_are_required(self):
        self.assertIn("service='geoflow-stabilized.service'", self.source)
        self.assertIn("production_worktree_dirty", self.source)
        self.assertIn("candidate_worktree_dirty", self.source)
        self.assertIn("GroupDBConfig", self.source)
        self.assertIn("SET LOCAL TRANSACTION READ ONLY", self.source)
        self.assertIn("is_tenant_db_secret_reference", self.source)
        self.assertIn("resolve_tenant_db_password", self.source)
        self.assertIn("active_tenants", self.source)
        self.assertIn("employee_soft_delete_activation_blocker=no_active_tenants", self.source)
        self.assertIn("not_all_active_tenants_accounted", self.source)
        self.assertIn("employee_soft_delete_activation_tenant_failure=", self.source)
        self.assertIn("group_id:{cfg.group_id}", self.source)
        self.assertIn("pgcode:{pgcode}", self.source)

    def test_dependency_table_and_migration_record_are_prechecked(self):
        self.assertIn('DEPENDENCY = "0026_contract_completion_event_backfill"', self.source)
        self.assertIn('MIGRATION = "0027_employee_profile_soft_delete"', self.source)
        self.assertIn('exists(cur, "hr.employee_profile")', self.source)
        self.assertIn('exists(cur, "public.django_migrations")', self.source)
        self.assertIn("0026 dependency not applied", self.source)
        self.assertIn("0027 migration record missing", self.source)

    def test_schema_application_is_additive_and_fully_postchecked(self):
        for column in (
            "is_deleted",
            "deleted_at",
            "deleted_by",
            "delete_reason",
            "restored_at",
            "restored_by",
        ):
            self.assertIn(column, self.source)
        self.assertIn("ADD COLUMN IF NOT EXISTS", self.source)
        self.assertIn("CREATE INDEX IF NOT EXISTS idx_employee_profile_active_name", self.source)
        self.assertLess(self.source.index("apply_0027(cur)", self.source.index("before = int")), self.source.index("if not already:"))
        self.assertIn("information_schema.columns", self.source)
        self.assertIn("is_nullable", self.source)
        self.assertIn("column_default", self.source)
        self.assertIn('exists(cur, "hr.idx_employee_profile_active_name")', self.source)
        self.assertIn("FROM pg_indexes", self.source)
        self.assertIn('"(name, email)" not in normalized_index', self.source)
        self.assertIn('"is_deleted = false" not in normalized_index', self.source)
        self.assertIn("employee profile row count changed", self.source)
        for forbidden in ("delete from", "drop table", "drop column", "truncate "):
            self.assertNotIn(forbidden, self.lowered)

    def test_schema_completes_before_code_checkout_and_runtime_health(self):
        db_complete = self.source.index("employee_soft_delete_activation_db_complete=yes")
        code_checkout = self.source.index('git -C "$repo" checkout -B "$expected_branch" "$candidate_sha"')
        self.assertLess(db_complete, code_checkout)
        for token in (
            "pip check",
            '"$repo/manage.py" check',
            "collectstatic --noinput",
            'systemctl restart "$service"',
            "https://geoflow.co.kr/login/",
            "employee_soft_delete_activation_public_login_status",
        ):
            self.assertIn(token, self.source)

    def test_failure_rolls_back_code_only_and_retains_additive_schema(self):
        self.assertIn("employee_soft_delete_activation_code_rollback_started=yes", self.source)
        self.assertIn("employee_soft_delete_activation_additive_schema_retained=yes", self.source)
        self.assertIn('checkout -B "$previous_branch" "$previous_sha"', self.source)

    def test_workboard_code_only_deploy_defers_when_0027_is_in_release(self):
        self.assertIn("geoflow_ops/migrations/0027_employee_profile_soft_delete.py", self.workboard)
        self.assertIn("requires_employee_soft_delete_activation", self.workboard)
        self.assertIn(
            "needs.classify-workboard-deploy.outputs.requires_employee_soft_delete_activation != 'true'",
            self.workboard,
        )

    def test_myinfo_activation_also_defers_when_0027_is_in_release(self):
        self.assertIn("geoflow_ops/migrations/0027_employee_profile_soft_delete.py", self.myinfo)
        self.assertIn("requires_employee_soft_delete_activation", self.myinfo)
        self.assertIn(
            "needs.classify-myinfo-hr-activation.outputs.requires_employee_soft_delete_activation != 'true'",
            self.myinfo,
        )


if __name__ == "__main__":
    unittest.main()
