from __future__ import annotations

from contextlib import nullcontext
from dataclasses import dataclass, field
from pathlib import Path
from unittest import TestCase
from unittest.mock import patch

from control.services.signup_account_decision_service import (
    SignupAccountDecision,
    decide_signup_account,
)
from control.services.signup_service import (
    SignupRequestInput,
    create_signup_request,
)
from control.services.signup_verification_service import (
    EmailVerificationGrant,
    verify_signup_email,
)


@dataclass
class LifecycleState:
    user_id: str = "user-reference"
    signup_request_id: str = "request-reference"
    user_created: bool = False
    email_verified: bool = False
    is_active: bool = False
    request_status: str | None = None
    request_version: int = 0
    events: list[str] = field(default_factory=list)
    membership_writes: int = 0


class FakeSignupRepository:
    alias = "central"

    def __init__(self, state: LifecycleState):
        self.state = state

    def account_exists(self, email: str) -> bool:
        return self.state.user_created

    def create_inactive_user(self, **values) -> str:
        self.state.user_created = True
        self.state.email_verified = False
        self.state.is_active = False
        return self.state.user_id

    def create_signup_request(self, **values) -> str:
        if values["user_id"] != self.state.user_id:
            raise AssertionError("signup request must bind to the created user")
        self.state.request_status = "pending_email_verification"
        self.state.request_version = 1
        return self.state.signup_request_id

    def append_submitted_event(self, **values) -> None:
        self.state.events.append("submitted")


class FakeVerificationTokenVerifier:
    alias = "central"

    def __init__(self, state: LifecycleState):
        self.state = state
        self.used = False

    def consume(self, token: str) -> EmailVerificationGrant | None:
        if self.used or token != "verification-token":
            return None
        self.used = True
        return EmailVerificationGrant(
            user_id=self.state.user_id,
            signup_request_id=self.state.signup_request_id,
        )


class FakeVerificationRepository:
    alias = "central"

    def __init__(self, state: LifecycleState):
        self.state = state

    def transition_request_to_pending_approval(
        self,
        *,
        signup_request_id: str,
        user_id: str,
        changed_at,
    ) -> bool:
        if (
            signup_request_id != self.state.signup_request_id
            or user_id != self.state.user_id
            or self.state.request_status != "pending_email_verification"
        ):
            return False
        self.state.request_status = "pending_approval"
        self.state.request_version += 1
        return True

    def mark_email_verified(self, *, user_id: str, changed_at) -> bool:
        if user_id != self.state.user_id or self.state.is_active:
            return False
        self.state.email_verified = True
        return True

    def append_verified_event(self, *, signup_request_id: str, created_at) -> None:
        self.state.events.append("verified")


class FakeDecisionRepository:
    alias = "central"

    def __init__(self, state: LifecycleState):
        self.state = state

    def apply_request_decision(self, *, decision, decided_at) -> str | None:
        if (
            decision.signup_request_id != self.state.signup_request_id
            or self.state.request_status != "pending_approval"
            or decision.expected_version != self.state.request_version
            or not self.state.email_verified
            or self.state.is_active
        ):
            return None
        self.state.request_status = decision.decision
        self.state.request_version += 1
        return self.state.user_id

    def activate_verified_user(self, *, user_id: str, changed_at) -> bool:
        if (
            user_id != self.state.user_id
            or not self.state.email_verified
            or self.state.is_active
        ):
            return False
        self.state.is_active = True
        return True

    def append_decision_event(
        self,
        *,
        signup_request_id: str,
        actor_user_id: str,
        decision: str,
        reason_code: str | None,
        created_at,
    ) -> None:
        self.state.events.append(decision)


class SignupLoginLifecycleContractTests(TestCase):
    def setUp(self):
        self.state = LifecycleState()
        self.input = SignupRequestInput(
            email="applicant@example.com",
            password="strong-password-value",
            name_display="Applicant",
            contact_phone="",
            organization_name="Organization",
            signup_purpose="GeoFlow work",
            terms_agreed=True,
            privacy_agreed=True,
        )

    @patch(
        "control.services.signup_service.make_password",
        return_value="stored-password-hash",
    )
    def test_signup_verification_and_approval_form_one_account_lifecycle(
        self,
        _make_password,
    ):
        receipt = create_signup_request(
            self.input,
            repository=FakeSignupRepository(self.state),
            atomic_context=nullcontext(),
        )

        self.assertEqual(receipt.user_id, self.state.user_id)
        self.assertFalse(self.state.email_verified)
        self.assertFalse(self.state.is_active)
        self.assertEqual(self.state.request_status, "pending_email_verification")
        self.assertEqual(self.state.request_version, 1)
        self.assertEqual(self.state.events, ["submitted"])

        verify_signup_email(
            "verification-token",
            token_verifier=FakeVerificationTokenVerifier(self.state),
            repository=FakeVerificationRepository(self.state),
            atomic_context=nullcontext(),
        )

        self.assertTrue(self.state.email_verified)
        self.assertFalse(self.state.is_active)
        self.assertEqual(self.state.request_status, "pending_approval")
        self.assertEqual(self.state.request_version, 2)
        self.assertEqual(self.state.events, ["submitted", "verified"])

        decide_signup_account(
            SignupAccountDecision(
                signup_request_id=self.state.signup_request_id,
                expected_version=2,
                actor_user_id="admin-reference",
                decision="approved",
                reason_code=None,
            ),
            repository=FakeDecisionRepository(self.state),
            atomic_context=nullcontext(),
        )

        self.assertTrue(self.state.email_verified)
        self.assertTrue(self.state.is_active)
        self.assertEqual(self.state.request_status, "approved")
        self.assertEqual(self.state.request_version, 3)
        self.assertEqual(self.state.events, ["submitted", "verified", "approved"])
        self.assertEqual(self.state.membership_writes, 0)

    @patch(
        "control.services.signup_service.make_password",
        return_value="stored-password-hash",
    )
    def test_rejection_after_email_verification_keeps_account_inactive(
        self,
        _make_password,
    ):
        create_signup_request(
            self.input,
            repository=FakeSignupRepository(self.state),
            atomic_context=nullcontext(),
        )
        verify_signup_email(
            "verification-token",
            token_verifier=FakeVerificationTokenVerifier(self.state),
            repository=FakeVerificationRepository(self.state),
            atomic_context=nullcontext(),
        )

        decide_signup_account(
            SignupAccountDecision(
                signup_request_id=self.state.signup_request_id,
                expected_version=2,
                actor_user_id="admin-reference",
                decision="rejected",
                reason_code=None,
            ),
            repository=FakeDecisionRepository(self.state),
            atomic_context=nullcontext(),
        )

        self.assertTrue(self.state.email_verified)
        self.assertFalse(self.state.is_active)
        self.assertEqual(self.state.request_status, "rejected")
        self.assertEqual(self.state.request_version, 3)
        self.assertEqual(self.state.events, ["submitted", "verified", "rejected"])
        self.assertEqual(self.state.membership_writes, 0)

    def test_login_rejects_inactive_account_before_session_creation(self):
        source = (
            Path(__file__).resolve().parent / "views_auth.py"
        ).read_text(encoding="utf-8")

        self.assertIn("if is_active is not True:", source)
        self.assertIn("burn_central_login_password_check(pw)", source)
        self.assertIn('{"error": PUBLIC_LOGIN_ERROR}', source)

    def test_active_account_without_membership_routes_to_central_dashboard(self):
        source = (
            Path(__file__).resolve().parent / "views_auth.py"
        ).read_text(encoding="utf-8")

        self.assertIn('request.session["tenant_db_alias"] = central_alias', source)
        self.assertIn('return redirect("after_login")', source)
        self.assertIn('if alias == central_alias or not gid:', source)
        self.assertIn("return redirect('control:dashboard')", source)
