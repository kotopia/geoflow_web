from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github" / "workflows" / "role-assignment-postgres-integration.yml"
BOOTSTRAP = ROOT / "scripts" / "ci" / "bootstrap_role_assignment_schema.sql"
EXERCISE = ROOT / "scripts" / "ci" / "exercise_role_assignment_postgres.py"
HANDLER = ROOT / "control" / "views_user_assignment.py"


class RoleAssignmentPostgresContractTests(TestCase):
    def test_fixture_deliberately_has_no_membership_unique_constraint(self):
        text = BOOTSTRAP.read_text()
        membership = text.split("CREATE TABLE user_group_map", 1)[1]
        self.assertNotIn("UNIQUE (user_id, group_id)", membership)
        self.assertIn("user_id uuid NOT NULL", membership)
        self.assertIn("group_id uuid NOT NULL", membership)
        self.assertIn("role_id uuid NOT NULL", membership)

    def test_exercise_uses_real_assignment_handler_twice(self):
        text = EXERCISE.read_text()
        self.assertIn("unwrap(users_assign_group_admin)", text)
        self.assertIn("assign(ROLE_A_ID)", text)
        self.assertIn("assign(ROLE_B_ID)", text)
        self.assertIn("role_assignment_postgres_first_insert=yes", text)
        self.assertIn("role_assignment_postgres_update_existing=yes", text)
        self.assertIn("role_assignment_postgres_membership_count_after_update=1", text)

    def test_real_handler_does_not_depend_on_on_conflict_or_database_uuid_generation(self):
        text = HANDLER.read_text()
        self.assertNotIn("ON CONFLICT", text)
        self.assertNotIn("gen_random_uuid", text)
        self.assertIn("pbkdf2_sha256$%%", text)
        self.assertIn("UPDATE user_group_map", text)
        self.assertIn("INSERT INTO user_group_map", text)

    def test_workflow_uses_only_disposable_postgres(self):
        text = WORKFLOW.read_text()
        self.assertIn("postgis/postgis:16-3.4", text)
        self.assertIn("127.0.0.1", text)
        self.assertIn("bootstrap_role_assignment_schema.sql", text)
        self.assertIn("exercise_role_assignment_postgres.py", text)
        self.assertNotIn("environment: production", text)
        self.assertNotIn("secrets.", text)
        self.assertNotIn("ssh ", text)
        self.assertNotIn("scp ", text)

    def test_workflow_never_runs_on_production_push(self):
        text = WORKFLOW.read_text()
        self.assertIn("pull_request:", text)
        self.assertNotIn("\n  push:\n", text)
        self.assertIn("workflow_dispatch:", text)
