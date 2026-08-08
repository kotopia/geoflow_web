from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parent


class TenantJsonRendererXssTests(unittest.TestCase):
    def test_event_timeline_uses_text_dom_for_user_values(self):
        source = (ROOT / "static" / "geoflow_ops" / "js" / "process-events-ui.js").read_text(encoding="utf-8")
        self.assertIn("strong.textContent = ev.title", source)
        self.assertIn("memo.textContent", source)
        self.assertIn("span.textContent = filename", source)
        self.assertIn("span.title = filename", source)
        self.assertNotIn("li.innerHTML", source)

    def test_scope_json_values_are_not_html_interpolated(self):
        source = (ROOT / "static" / "geoflow_ops" / "js" / "scope-linker.js").read_text(encoding="utf-8")
        self.assertIn("name.textContent = String(row.name", source)
        self.assertIn("code.textContent = String(row.code", source)
        self.assertIn("input.value = String(value)", source)
        self.assertNotIn("data.l1_list.map", source)
        self.assertNotIn("rows.map(r =>", source)
