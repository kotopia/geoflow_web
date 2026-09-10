from __future__ import annotations

import inspect
from pathlib import Path

from django.http import Http404
from django.template.loader import get_template
from django.test import SimpleTestCase

from . import (
    qfield_device_views,
    qfield_sync_views,
    qfield_ticket_roaming_views,
    qfield_views,
    qgis_views,
    realtime_ticket_views,
    realtime_views,
    sync_views,
    views,
)
from .layer_plan import (
    DEFAULT_PROFILE_CODES,
    allowed_standard_names_for_projects,
    require_enabled_layer_plan,
)
from .registry import domain_counts_for_rows


class LayerPlanFailClosedTests(SimpleTestCase):
    def test_shared_guard_rejects_unready_and_scope_disabled_plans(self):
        with self.assertRaises(Http404):
            require_enabled_layer_plan({"ready": False, "gis_enabled": False})
        with self.assertRaises(Http404):
            require_enabled_layer_plan({"ready": True, "gis_enabled": False})

        plan = {"ready": True, "gis_enabled": True, "layers": []}
        self.assertIs(require_enabled_layer_plan(plan), plan)

    def test_all_project_data_transports_use_the_shared_guard(self):
        guarded_functions = (
            qgis_views._require_project,
            qfield_views._require_project,
            qfield_device_views._project_and_plan,
            qfield_ticket_roaming_views._ticket_project_and_plan,
            realtime_views._require_project,
            realtime_ticket_views.qgis_project_realtime_ticket_api,
            sync_views._require_project,
            qfield_sync_views._ticket_project_and_plan,
        )
        for function in guarded_functions:
            with self.subTest(function=function.__module__ + "." + function.__name__):
                self.assertIn(
                    "require_enabled_layer_plan(plan)", inspect.getsource(function)
                )

    def test_project_page_never_substitutes_full_registry_for_empty_plan(self):
        source = inspect.getsource(views.project_dashboard)
        self.assertIn("allowed = allowed_standard_names(plan)", source)
        self.assertNotIn(
            "allowed_standard_names(plan) if plan.get(\"ready\") else None", source
        )

    def test_registry_counts_are_project_authorization_scoped(self):
        source = inspect.getsource(views._physical_feature_rows)
        self.assertIn("project_id = ANY(%s::uuid[])", source)
        endpoint = inspect.getsource(views.layer_registry_api)
        self.assertIn("policy.visible_project_ids()", endpoint)
        self.assertIn("gis_foundation_unavailable", endpoint)
        self.assertIn("allowed_standard_names_for_projects", endpoint)

    def test_dashboard_layer_union_uses_project_and_profile_scope(self):
        self.assertEqual(allowed_standard_names_for_projects("unused", []), set())
        source = inspect.getsource(allowed_standard_names_for_projects)
        self.assertIn("s.project_id=ANY(%s::uuid[])", source)
        self.assertIn("pp.project_id=rp.project_id", source)
        self.assertIn("p.code=ANY(%s::text[])", source)
        self.assertIn("array_position(%s::text[], p.code)", source)
        self.assertIn("pf.profile_id=sp.profile_id", source)
        self.assertIn("cf.capability_id=c.id", source)

    def test_unassigned_project_prefers_production_profile_then_dev_compatibility(self):
        self.assertEqual(
            DEFAULT_PROFILE_CODES,
            ("GEOFLOW_BASE_V1", "GEOFLOW_DEV_BASE"),
        )

    def test_domain_summary_contains_only_authorized_rows(self):
        counts = domain_counts_for_rows(
            [
                {"domain": "COMMON"},
                {"domain": "WTL"},
                {"domain": "WTL"},
            ]
        )
        self.assertEqual(
            counts,
            [
                {"code": "COMMON", "label": "공통", "count": 1},
                {"code": "WTL", "label": "상수", "count": 2},
            ],
        )
        self.assertNotIn("domain_counts()", inspect.getsource(views.dashboard))
        self.assertNotIn("domain_counts()", inspect.getsource(views.project_dashboard))

    def test_unready_ui_explains_block_and_disables_client_handoffs(self):
        template = (
            Path(__file__).resolve().parents[1]
            / "templates"
            / "geoflow_ops"
            / "gis"
            / "project_dashboard.html"
        ).read_text(encoding="utf-8")
        self.assertIn("GIS 공통기반이 이 tenant에 적용되지 않았습니다.", template)
        self.assertIn("{% if not layer_plan.ready or not layer_plan.gis_enabled %}disabled{% endif %}", template)
        self.assertIn("프로젝트 레이어를 임의로 대체하지 않으며", template)
        get_template("geoflow_ops/gis/project_dashboard.html")
        get_template("geoflow_ops/gis/dashboard.html")
