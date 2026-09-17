from __future__ import annotations

import inspect
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
from uuid import uuid4

from django.http import Http404
from django.template.loader import get_template
from django.test import SimpleTestCase

from geoflow_ops.models import ProjectScopeItem

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
    allowed_standard_names_for_projects,
    project_layer_plan,
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

    def test_dashboard_layer_union_uses_each_central_project_plan(self):
        self.assertEqual(allowed_standard_names_for_projects("unused", []), set())
        source = inspect.getsource(allowed_standard_names_for_projects)
        self.assertIn("central_definitions.central_snapshot()", source)
        self.assertIn("_scope_rows(cursor, project_ids=ids)", source)
        self.assertNotIn("gis.profile", source)
        plan_source=inspect.getsource(project_layer_plan)
        self.assertIn("central_definitions.central_snapshot()",plan_source)
        self.assertNotIn("gis.profile",plan_source)
        self.assertNotIn("gis.capability",plan_source)

    def test_tenant_profiles_are_not_definition_fallbacks(self):
        source=Path(__file__).with_name('layer_plan.py').read_text(encoding='utf-8')
        for legacy in ('gis.profile','gis.profile_field','gis.capability','gis.scope_binding'):
            self.assertNotIn(legacy,source)

    def test_scope_queries_match_the_canonical_tenant_schema(self):
        model_columns = {
            field.column for field in ProjectScopeItem._meta.local_fields
        }
        self.assertNotIn("active", model_columns)
        self.assertTrue(
            {"project_id", "lv2_id", "lv3_id", "lv4_id"}.issubset(model_columns)
        )

        source = Path(__file__).with_name("layer_plan.py").read_text(
            encoding="utf-8"
        )
        self.assertEqual(source.count("FROM prj.scope_item"), 1)
        self.assertNotIn("COALESCE(active", source)
        self.assertNotIn("scope_item WHERE active", source)

    def test_qgis_projects_endpoint_renders_central_plan_without_legacy_scope_column(self):
        project = SimpleNamespace(
            id=uuid4(), code="26003", name="QGIS smoke", status="active"
        )

        class QuerySet:
            def filter(self, **kwargs):
                return self

            def __getitem__(self, value):
                return [project][value]

        policy = SimpleNamespace(
            mode="full",
            visible_project_ids=lambda: None,
            membership=lambda project_id: {"member_role": "project_manager"},
            can_webgis_write=lambda project_id: True,
        )
        plan = {
            "ready": True,
            "gis_enabled": True,
            "definition": {"version": 3, "revision": "revision"},
            "capabilities": [{"catalog_level": 2, "catalog_item_id": "catalog"}],
            "layers": [{"standard_name": "WTL_PIPE_LM"}],
        }
        request = SimpleNamespace(method="GET")
        endpoint = inspect.unwrap(qgis_views.qgis_projects_api)
        with (
            patch.object(qgis_views, "_require_qgis_context", return_value="tenant"),
            patch.object(qgis_views, "project_access_policy", return_value=policy),
            patch.object(qgis_views, "_project_queryset", return_value=QuerySet()),
            patch.object(qgis_views, "gis_enabled_project_ids", return_value={str(project.id)}),
            patch.object(qgis_views, "project_layer_plan", return_value=plan),
            patch.object(
                qgis_views,
                "current_user_context",
                return_value={"worker_link_status": "linked"},
            ),
        ):
            response = endpoint(request)

        payload = json.loads(response.content)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(payload["count"], 1)
        self.assertEqual(payload["results"][0]["layer_count"], 1)
        self.assertEqual(payload["results"][0]["definition"]["revision"], "revision")

    def test_release_runs_read_only_qgis_runtime_smoke(self):
        root = Path(__file__).resolve().parents[2]
        command = (
            root
            / "control/management/commands/smoke_qgis_project_runtime.py"
        ).read_text(encoding="utf-8")
        workflow = (
            root / ".github/workflows/gis-definition-code-deploy.yml"
        ).read_text(encoding="utf-8")

        self.assertIn("tenant_cursor(config.group_id, write=False)", command)
        self.assertIn("layer_plan._scope_rows(cursor)", command)
        self.assertIn("central_definitions.resolve", command)
        self.assertIn("qgis_runtime_projects_openable", command)
        self.assertIn("smoke_qgis_project_runtime", workflow)
        self.assertIn("PGOPTIONS='-c default_transaction_read_only=on'", workflow)

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
