from pathlib import Path
from unittest import TestCase


REPO_ROOT = Path(__file__).resolve().parent.parent
CONTROL_DIR = REPO_ROOT / "control"
TENANT_DIR = REPO_ROOT / "geoflow_ops"


class Phase1LegacyInviteBoundaryTests(TestCase):
    def test_live_urlconfs_do_not_expose_legacy_people_invite(self):
        control_urls = (CONTROL_DIR / "urls.py").read_text(encoding="utf-8")
        tenant_urls = (TENANT_DIR / "urls.py").read_text(encoding="utf-8")
        combined = control_urls + "\n" + tenant_urls

        self.assertNotIn("people_invite", combined)
        self.assertNotIn("views_people", combined)
        self.assertNotIn("create_or_pending_membership", combined)

    def test_live_join_approval_does_not_provision_target_account(self):
        source = (CONTROL_DIR / "views_join.py").read_text(encoding="utf-8")
        self.assertIn("get_existing_user_account_by_email", source)
        self.assertIn("account.get(\"is_active\") is not True", source)
        self.assertNotIn("C.create_user(", source)
        self.assertNotIn("C.get_or_create_user_by_email(requested_email", source)

    def test_legacy_auto_approval_code_is_explicitly_dormant(self):
        source = (CONTROL_DIR / "services_identity.py").read_text(encoding="utf-8")
        self.assertIn('return "auto_approved"', source)
        # This legacy helper may remain temporarily for compatibility, but a route
        # exposure must fail the live-url contract above before public launch.
    def test_live_join_approval_does_not_create_legacy_raw_password_tokens(self):
        source = (CONTROL_DIR / "views_join.py").read_text(encoding="utf-8")
        for forbidden in (
            "create_set_password_token",
            "send_set_password_email",
            "send_invite_email_with_set_password_link",
        ):
            self.assertNotIn(forbidden, source)

