from datetime import datetime, timezone
from inspect import getsource
from unittest import TestCase
from unittest.mock import MagicMock

from control.services.signup_review_query_service import (
    CentralSignupReviewQueryRepository,
    PendingSignupReviewDetail,
    PendingSignupReviewListItem,
    get_pending_signup_review,
    list_pending_signup_reviews,
)


class SignupReviewQueryServiceTests(TestCase):
    def setUp(self):
        self.repository = MagicMock()
        self.submitted_at = datetime(2026, 8, 6, 10, 0, tzinfo=timezone.utc)
        self.verified_at = datetime(2026, 8, 6, 10, 5, tzinfo=timezone.utc)
        self.item = PendingSignupReviewListItem(
            signup_request_id="request-reference",
            user_id="user-reference",
            email="applicant@example.com",
            name_display="신청자",
            organization_name="기관",
            version=2,
            submitted_at=self.submitted_at,
            verified_at=self.verified_at,
        )
        self.detail = PendingSignupReviewDetail(
            signup_request_id="request-reference",
            user_id="user-reference",
            email="applicant@example.com",
            name_display="신청자",
            contact_phone="010-0000-0000",
            organization_name="기관",
            signup_purpose="업무 활용",
            terms_version="terms-v1",
            terms_accepted_at=self.submitted_at,
            privacy_version="privacy-v1",
            privacy_accepted_at=self.submitted_at,
            version=2,
            submitted_at=self.submitted_at,
            verified_at=self.verified_at,
        )

    def test_list_uses_bounded_pagination_and_returns_repository_items(self):
        self.repository.list_pending_approval.return_value = (self.item,)

        result = list_pending_signup_reviews(
            limit=25,
            offset=50,
            repository=self.repository,
        )

        self.assertEqual(result, (self.item,))
        self.repository.list_pending_approval.assert_called_once_with(
            limit=25,
            offset=50,
        )

    def test_detail_normalizes_identifier_and_preserves_stale_as_none(self):
        self.repository.get_pending_approval.return_value = self.detail

        result = get_pending_signup_review(
            " request-reference ",
            repository=self.repository,
        )

        self.assertEqual(result, self.detail)
        self.repository.get_pending_approval.assert_called_once_with(
            signup_request_id="request-reference"
        )

        self.repository.get_pending_approval.return_value = None
        self.assertIsNone(
            get_pending_signup_review(
                "request-reference",
                repository=self.repository,
            )
        )

    def test_review_dto_repr_hides_identifiers_and_applicant_pii(self):
        for dto in (self.item, self.detail):
            rendered = repr(dto)
            for sensitive in (
                "request-reference",
                "user-reference",
                "applicant@example.com",
                "신청자",
                "기관",
            ):
                self.assertNotIn(sensitive, rendered)
        self.assertNotIn("010-0000-0000", repr(self.detail))
        self.assertNotIn("업무 활용", repr(self.detail))

    def test_invalid_pagination_and_empty_identifier_fail_before_repository(self):
        invalid_pages = (
            {"limit": 0, "offset": 0},
            {"limit": 201, "offset": 0},
            {"limit": 10, "offset": -1},
            {"limit": 10, "offset": 100_001},
        )
        for values in invalid_pages:
            with self.subTest(values=values):
                with self.assertRaises(ValueError):
                    list_pending_signup_reviews(
                        repository=self.repository,
                        **values,
                    )
        with self.assertRaises(ValueError):
            get_pending_signup_review(" ", repository=self.repository)

        self.repository.list_pending_approval.assert_not_called()
        self.repository.get_pending_approval.assert_not_called()

    def test_repository_queries_only_verified_inactive_pending_approval(self):
        source = getsource(CentralSignupReviewQueryRepository)
        for contract in (
            "signup_request.status='pending_approval'",
            "signup_user.email_verified=TRUE",
            "signup_user.is_active=FALSE",
            "signup_event.event_type='verified'",
            "LIMIT %s OFFSET %s",
        ):
            self.assertIn(contract, source)
        for forbidden in (
            "password_hash",
            "token_digest",
            "join_requests",
            "user_group_map",
            "employee_profile",
            "db_password",
        ):
            self.assertNotIn(forbidden, source)
