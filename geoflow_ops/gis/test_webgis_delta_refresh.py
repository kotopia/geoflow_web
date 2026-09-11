from __future__ import annotations

import inspect
from pathlib import Path

from django.template.loader import get_template
from django.test import SimpleTestCase

from . import views


class WebgisDeltaRefreshTests(SimpleTestCase):
    def test_project_page_exposes_delta_cursor_and_endpoint(self):
        template_path = (
            Path(__file__).resolve().parents[1]
            / "templates/geoflow_ops/gis/project_dashboard.html"
        )
        source = template_path.read_text(encoding="utf-8")
        self.assertIn("data-delta-url=", source)
        self.assertIn("gis:project_delta_api", source)
        self.assertIn('data-current-revision="{{ webgis_revision|default:0 }}"', source)
        get_template("geoflow_ops/gis/project_dashboard.html")

    def test_ready_empty_layers_are_available_for_new_feature_refresh(self):
        source = inspect.getsource(views.project_dashboard)
        self.assertIn('if row["physical_status"] == "READY"', source)
        self.assertNotIn('and (row["row_count"] or 0) > 0', source)

    def test_browser_polls_revision_delta_and_refreshes_changed_ids(self):
        script = (
            Path(__file__).resolve().parents[1]
            / "static/geoflow_ops/js/gis-project-map.js"
        ).read_text(encoding="utf-8")
        self.assertIn('new URLSearchParams({ since:', script)
        self.assertIn('await applyRealtimeEvent({', script)
        self.assertIn('data-current-revision', script)
        self.assertIn('document.hidden ? 15000 : 5000', script)
        self.assertIn('data.snapshot_required', script)
        self.assertIn('Number(state.info.row_count || 0) > 0', script)
