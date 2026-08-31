from pathlib import Path

from django.test import SimpleTestCase

from geoflow_ops.views_dashboard import _parse_bool, _parse_year, _status_group
from geoflow_ops.views_execution import _completion_validation, _parse_decimal


ROOT = Path(__file__).resolve().parent


class Phase4TaskExecutionRuleTests(SimpleTestCase):
    def test_completion_allows_equal_quantities_without_reason(self):
        self.assertIsNone(_completion_validation("done", 10, 10, ""))

    def test_completion_requires_reason_when_quantities_differ(self):
        self.assertIsNotNone(_completion_validation("done", 10, 8, ""))
        self.assertIsNone(_completion_validation("done", 10, 8, "현장 여건 변경"))

    def test_non_complete_state_never_requires_variance_reason(self):
        self.assertIsNone(_completion_validation("active", 10, 8, ""))

    def test_decimal_parser_rejects_invalid_nonblank_value(self):
        value, error = _parse_decimal("abc", field="실적 물량")
        self.assertIsNone(value)
        self.assertTrue(error)


class Phase4DashboardFilterTests(SimpleTestCase):
    def test_status_group_uses_project_execution_vocabulary(self):
        self.assertEqual(_status_group("active"), "active")
        self.assertEqual(_status_group("완료"), "complete")
        self.assertEqual(_status_group("paused"), "pause")

    def test_year_and_boolean_filters_fail_closed(self):
        self.assertEqual(_parse_year("2026"), 2026)
        self.assertIsNone(_parse_year("not-a-year"))
        self.assertTrue(_parse_bool("1"))
        self.assertFalse(_parse_bool("0"))


class Phase4TaskMigrationContractTests(SimpleTestCase):
    def test_migration_is_additive_and_preserves_existing_scope_rows(self):
        source = (ROOT / "migrations" / "0020_phase4_project_task_execution.py").read_text(encoding="utf-8")
        lowered = source.lower()
        self.assertIn("add column if not exists progress_qty", lowered)
        self.assertIn("add column if not exists status", lowered)
        self.assertIn("add column if not exists completed_at", lowered)
        self.assertIn("add column if not exists assignee_employee_id", lowered)
        self.assertIn("add column if not exists variance_reason", lowered)
        self.assertNotIn("delete from prj.scope_item", lowered)
        self.assertNotIn("truncate prj.scope_item", lowered)
        self.assertNotIn("drop table prj.scope_item", lowered)
        self.assertIn("nothing is auto-declared complete", lowered)

    def test_execution_view_keeps_project_scope_on_every_update(self):
        source = (ROOT / "views_execution.py").read_text(encoding="utf-8")
        self.assertIn("WHERE id=%s AND project_id=%s", source)
        self.assertIn("project task update lost scope", source)
        self.assertIn('gf_perm_required("projects.edit")', source)

    def test_dashboard_is_permission_aware_and_contract_terminal_lineage_is_event_only(self):
        source = (ROOT / "views_dashboard.py").read_text(encoding="utf-8")
        self.assertIn('gf_has_perm(request, "projects.view")', source)
        self.assertIn('gf_has_perm(request, "contracts.view")', source)
        self.assertIn('gf_has_perm(request, "directory.view")', source)
        self.assertIn("qs.exclude(status__in=", source)
        self.assertIn("def _terminal_contract_ids", source)
        self.assertIn("'closeout_approved'", source)
        self.assertIn("'closeout_complete'", source)
        self.assertIn("'contract_cancel'", source)
        self.assertIn("exclude(contract_id__in=terminal_contract_ids)", source)
        self.assertNotIn("FROM ctr.contracts", source.split("def _terminal_contract_ids", 1)[1].split("def _task_rows", 1)[0])
        self.assertNotIn("exclude(contract__status__in=terminal)", source)

    def test_legacy_completed_contracts_are_migrated_to_completion_events(self):
        migration = (ROOT / "migrations" / "0026_contract_completion_event_backfill.py").read_text(encoding="utf-8")
        lowered = migration.lower()
        self.assertIn("'closeout_complete'", migration)
        self.assertIn("legacy_contract_status_migration", migration)
        self.assertIn("system:migration:0026", migration)
        self.assertIn("c.end_date", migration)
        self.assertIn("occurred_at_inferred", migration)
        self.assertIn("SET status = NULL", migration)
        self.assertIn("NOT EXISTS", migration)
        self.assertNotIn("DELETE FROM ctr.contracts", migration.upper())
        self.assertNotIn("TRUNCATE ctr.contracts", migration.upper())
        self.assertNotIn("DROP TABLE ctr.contracts", migration.upper())
