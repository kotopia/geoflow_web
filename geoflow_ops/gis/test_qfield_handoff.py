from __future__ import annotations

from django.core.cache import cache
from django.test import SimpleTestCase

from .qfield_handoff import consume_pending_handoff, stage_pending_handoff


class QFieldPendingHandoffTests(SimpleTestCase):
    project_id = "11111111-1111-4111-8111-111111111401"
    user_id = "1"
    group_id = "90000000-0000-4000-8000-000000000201"
    install_id = "geoflow-11111111-1111-4111-8111-111111111401"

    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def test_pending_handoff_is_consumed_once(self):
        stage_pending_handoff(
            project_id=self.project_id,
            user_id=self.user_id,
            group_id=self.group_id,
            install_id=self.install_id,
            handoff_token="browser-handoff",
        )
        self.assertEqual(
            consume_pending_handoff(
                project_id=self.project_id,
                user_id=self.user_id,
                group_id=self.group_id,
                install_id=self.install_id,
            ),
            "browser-handoff",
        )
        self.assertEqual(
            consume_pending_handoff(
                project_id=self.project_id,
                user_id=self.user_id,
                group_id=self.group_id,
                install_id=self.install_id,
            ),
            "",
        )

    def test_pending_handoff_is_bound_to_install_and_user(self):
        stage_pending_handoff(
            project_id=self.project_id,
            user_id=self.user_id,
            group_id=self.group_id,
            install_id=self.install_id,
            handoff_token="browser-handoff",
        )
        self.assertEqual(
            consume_pending_handoff(
                project_id=self.project_id,
                user_id="2",
                group_id=self.group_id,
                install_id=self.install_id,
            ),
            "",
        )
        self.assertEqual(
            consume_pending_handoff(
                project_id=self.project_id,
                user_id=self.user_id,
                group_id=self.group_id,
                install_id=self.install_id + "-other",
            ),
            "",
        )
