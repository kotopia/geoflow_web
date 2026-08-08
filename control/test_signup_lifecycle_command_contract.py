from pathlib import Path
from unittest import TestCase


ROOT = Path(__file__).resolve().parent
COMMAND = ROOT / "management" / "commands" / "expire_signup_lifecycle.py"


class SignupLifecycleCommandContractTests(TestCase):
    def test_command_is_dry_run_without_execute_and_uses_bounded_defaults(self):
        source = COMMAND.read_text(encoding="utf-8")
        self.assertIn("UNVERIFIED_EXPIRY_DAYS = 7", source)
        self.assertIn("PENDING_APPROVAL_EXPIRY_DAYS = 30", source)
        self.assertIn('"--execute"', source)
        self.assertIn("if not options[\"execute\"]", source)
        self.assertIn("no database query/write performed", source)
        self.assertIn("1 <= batch_size <= 500", source)

    def test_execute_calls_existing_expiration_service_for_only_pending_states(self):
        source = COMMAND.read_text(encoding="utf-8")
        self.assertIn('status="pending_email_verification"', source)
        self.assertIn('status="pending_approval"', source)
        for terminal in ('status="approved"', 'status="rejected"', 'status="expired"'):
            self.assertNotIn(terminal, source)
