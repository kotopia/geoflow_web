from inspect import getsource
from unittest import TestCase

from control.services.signup_request_expiration_service import (
    CentralSignupRequestExpirationRepository,
)


class SignupExpirationDeliveryRaceContractTests(TestCase):
    def test_live_delivery_lease_defers_expiration(self):
        source = getsource(CentralSignupRequestExpirationRepository.expire_batch)
        self.assertIn("signup_verification_delivery_outbox", source)
        self.assertIn("active_delivery.status='processing'", source)
        self.assertIn("active_delivery.claim_expires_at > %s", source)
        self.assertIn("NOT EXISTS", source)

    def test_expiration_still_uses_bounded_locked_batch(self):
        source = getsource(CentralSignupRequestExpirationRepository.expire_batch)
        self.assertIn("FOR UPDATE OF signup_request SKIP LOCKED", source)
        self.assertIn("LIMIT %s", source)
        self.assertIn("signup_user.is_active=FALSE", source)
