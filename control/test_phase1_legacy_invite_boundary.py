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

    def test_legacy_membership_helper_cannot_auto_approve(self):
        source = (CONTROL_DIR / "services_identity.py").read_text(encoding="utf-8")
        self.assertNotIn('return "auto_approved"', source)
        self.assertNotIn("allowed_domains", source)
        self.assertIn("status='pending'", source)
        self.assertIn('return "pending"', source)

    def test_legacy_implicit_account_provisioning_is_disabled(self):
        source = (CONTROL_DIR / "services_identity.py").read_text(encoding="utf-8")
        self.assertIn("Legacy implicit central account provisioning is disabled", source)
        self.assertNotIn("VALUES (%s,'!',TRUE,%s)", source)

    def test_live_join_approval_does_not_create_legacy_raw_password_tokens(self):
        source = (CONTROL_DIR / "views_join.py").read_text(encoding="utf-8")
        for forbidden in (
            "create_set_password_token",
            "send_set_password_email",
            "send_invite_email_with_set_password_link",
        ):
            self.assertNotIn(forbidden, source)

    def test_legacy_invitation_mail_service_is_disabled(self):
        source = (CONTROL_DIR / "services_mail.py").read_text(encoding="utf-8")
        self.assertIn("Legacy invitation password email is disabled", source)
        self.assertNotIn("INSERT INTO password_reset_tokens", source)
        self.assertNotIn("send_mail(", source)
