from __future__ import annotations

from contextlib import ExitStack, nullcontext
from decimal import Decimal
from unittest.mock import MagicMock, patch

from django.test import SimpleTestCase
from django.urls import resolve, reverse

from . import survey_link_views
from .qgis_sync import SyncConflict, SyncRejected
from .survey_links import (
    _optional_decimal,
    apply_survey_link_changeset,
    list_survey_links,
)


class SurveyLinkContractTests(SimpleTestCase):
    project_id = "11111111-1111-4111-8111-111111111401"
    client_id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    changeset_id = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
    link_id = "cccccccc-cccc-4ccc-8ccc-cccccccccccc"
    survey_id = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
    target_id = "eeeeeeee-eeee-4eee-8eee-eeeeeeeeeeee"

    def test_routes_expose_session_and_qfield_read_write_contracts(self):
        expected = {
            "project_survey_links_api": survey_link_views.project_survey_links_api,
            "project_survey_link_changeset_api": survey_link_views.project_survey_link_changeset_api,
            "qfield_survey_links_api": survey_link_views.qfield_survey_links_api,
            "qfield_survey_link_changeset_api": survey_link_views.qfield_survey_link_changeset_api,
        }
        for name, view in expected.items():
            with self.subTest(name=name):
                url = reverse(f"gis:{name}", kwargs={"project_id": self.project_id})
                self.assertIs(resolve(url).func, view)

    def test_distance_and_confidence_validation(self):
        self.assertEqual(
            _optional_decimal("1.25", field="distance", minimum=Decimal("0")),
            Decimal("1.25"),
        )
        self.assertIsNone(_optional_decimal("", field="distance"))
        for value in ("-0.1", "NaN", "Infinity", "not-a-number"):
            with self.subTest(value=value), self.assertRaises(SyncRejected):
                _optional_decimal(value, field="distance", minimum=Decimal("0"))
        with self.assertRaises(SyncRejected):
            _optional_decimal("1.01", field="confidence", maximum=Decimal("1"))

    def test_link_query_is_limited_to_active_layer_plan(self):
        plan = {"layers": [{"standard_name": "WTL_VALV_PS"}, {"standard_name": "SURVEY"}]}
        cursor = MagicMock()
        cursor.fetchall.return_value = []
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        with patch("geoflow_ops.gis.survey_links.connections", {"tenant": connection}):
            self.assertEqual(
                list_survey_links("tenant", project_id=self.project_id, plan=plan),
                [],
            )
        sql, params = cursor.execute.call_args.args
        self.assertIn("upper(ft.standard_name)=ANY(%s)", sql)
        self.assertEqual(params[1], ["WTL_VALV_PS"])

        with self.assertRaises(SyncRejected):
            list_survey_links(
                "tenant",
                project_id=self.project_id,
                plan=plan,
                standard_name="WTL_PIPE_LS",
            )

    def _payload(self):
        return {
            "client_id": self.client_id,
            "changeset_id": self.changeset_id,
            "base_revision": 4,
            "changes": [{
                "action": "create",
                "id": self.link_id,
                "survey_id": self.survey_id,
                "layer": "WTL_VALV_PS",
                "target_id": self.target_id,
                "match_method": "manual",
                "match_distance": "0.25",
                "match_confidence": "0.9",
            }],
        }

    def test_create_is_project_scoped_revisioned_and_idempotent(self):
        cursor = MagicMock()
        cursor.fetchone.return_value = None
        cursor.rowcount = 1
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        created = {
            "id": self.link_id,
            "survey_id": self.survey_id,
            "feature_type_id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
            "layer": "WTL_VALV_PS",
            "physical_name": "wtl_valv_ps",
            "target_id": self.target_id,
            "match_method": "manual",
            "match_distance": 0.25,
            "match_confidence": 0.9,
            "confirmed_by": None,
            "confirmed_at": "2026-09-08T00:00:00+00:00",
            "created_at": "2026-09-08T00:00:00+00:00",
        }
        with ExitStack() as stack:
            stack.enter_context(patch("geoflow_ops.gis.survey_links.changeset_runtime_enabled", return_value=True))
            stack.enter_context(patch("geoflow_ops.gis.survey_links._ensure_project_state", return_value=4))
            stack.enter_context(patch("geoflow_ops.gis.survey_links._receipt_replay", return_value=None))
            stack.enter_context(patch("geoflow_ops.gis.survey_links._reserve_receipt", return_value=True))
            stack.enter_context(patch("geoflow_ops.gis.survey_links._feature_type_for_layer", return_value={
                "id": created["feature_type_id"], "standard_name": "WTL_VALV_PS", "physical_name": "wtl_valv_ps",
            }))
            survey = stack.enter_context(patch("geoflow_ops.gis.survey_links._survey_exists", return_value=True))
            target = stack.enter_context(patch("geoflow_ops.gis.survey_links._target_exists", return_value=True))
            stack.enter_context(patch("geoflow_ops.gis.survey_links._link_by_id", return_value=created))
            stack.enter_context(patch("geoflow_ops.gis.survey_links._allocate_revisions", return_value=(5, 5, 5)))
            log = stack.enter_context(patch("geoflow_ops.gis.survey_links._insert_change_log"))
            stack.enter_context(patch("geoflow_ops.gis.survey_links.transaction.atomic", side_effect=lambda **_: nullcontext()))
            stack.enter_context(patch("geoflow_ops.gis.survey_links.connections", {"tenant": connection}))
            result = apply_survey_link_changeset(
                "tenant", project_id=self.project_id, plan={}, payload=self._payload()
            )

        self.assertEqual(result["protocol"], "survey_link_changeset_v1")
        self.assertEqual(result["created"], 1)
        self.assertEqual(result["current_revision"], 5)
        self.assertEqual(result["applied"][0]["resource_kind"], "relation")
        survey.assert_called_once_with(
            "tenant", project_id=self.project_id, survey_id=self.survey_id, lock=True
        )
        target.assert_called_once_with(
            "tenant", project_id=self.project_id, physical_name="wtl_valv_ps",
            target_id=self.target_id, lock=True,
        )
        self.assertEqual(log.call_args.kwargs["physical_name"], "survey_link")
        self.assertEqual(log.call_args.kwargs["new_values"]["target_id"], self.target_id)

    def test_missing_or_cross_project_target_is_rejected_before_insert(self):
        cursor = MagicMock()
        connection = MagicMock()
        connection.cursor.return_value.__enter__.return_value = cursor
        with ExitStack() as stack:
            for target, value in (
                ("changeset_runtime_enabled", True), ("_ensure_project_state", 4),
                ("_receipt_replay", None), ("_reserve_receipt", True),
                ("_survey_exists", True), ("_target_exists", False),
            ):
                stack.enter_context(patch(f"geoflow_ops.gis.survey_links.{target}", return_value=value))
            stack.enter_context(patch("geoflow_ops.gis.survey_links._feature_type_for_layer", return_value={
                "id": "ffffffff-ffff-4fff-8fff-ffffffffffff",
                "standard_name": "WTL_VALV_PS", "physical_name": "wtl_valv_ps",
            }))
            stack.enter_context(patch("geoflow_ops.gis.survey_links.transaction.atomic", side_effect=lambda **_: nullcontext()))
            stack.enter_context(patch("geoflow_ops.gis.survey_links.connections", {"tenant": connection}))
            with self.assertRaises(SyncConflict) as caught:
                apply_survey_link_changeset(
                    "tenant", project_id=self.project_id, plan={}, payload=self._payload()
                )
        self.assertEqual(caught.exception.conflicts[0]["reason"], "target_outside_project_or_missing")

    def test_committed_retry_returns_receipt_before_relation_validation(self):
        replay = {"ok": True, "replayed": True, "current_revision": 5}
        with ExitStack() as stack:
            stack.enter_context(patch("geoflow_ops.gis.survey_links.changeset_runtime_enabled", return_value=True))
            stack.enter_context(patch("geoflow_ops.gis.survey_links._ensure_project_state", return_value=5))
            stack.enter_context(patch("geoflow_ops.gis.survey_links._receipt_replay", return_value=replay))
            reserve = stack.enter_context(patch("geoflow_ops.gis.survey_links._reserve_receipt"))
            stack.enter_context(patch("geoflow_ops.gis.survey_links.transaction.atomic", side_effect=lambda **_: nullcontext()))
            result = apply_survey_link_changeset(
                "tenant", project_id=self.project_id, plan={}, payload=self._payload()
            )
        self.assertEqual(result, replay)
        reserve.assert_not_called()
