from pathlib import Path
import unittest

from control.services.gis_catalog_navigation import category_tree


ROOT = Path(__file__).resolve().parents[1]


class CategoryTreeTests(unittest.TestCase):
    class Cursor:
        def execute(self, sql):
            self.sql = sql
            if "FROM catalog.category_parent" in sql:
                self.description = [("parent_id",), ("child_id",)]
                self.values = [("l1", "l2-water")]
            else:
                self.description = [("id",), ("code",), ("name",), ("level",)]
                self.values = [
                    ("l1", "UTILITY", "업무유형", 1),
                    ("l2-water", "WATER", "업무범위", 2),
                ]

        def fetchall(self):
            return self.values

    def test_active_l1_l2_tree_is_shared_and_ordered(self):
        cursor = self.Cursor()
        result = category_tree(cursor)
        self.assertEqual([node["level"] for node in result["nodes"]], [1, 2])
        self.assertEqual(result["parents"], [{"parent_id": "l1", "child_id": "l2-water"}])
        self.assertIn("parent.active", cursor.sql)
        self.assertIn("child.active", cursor.sql)


class CentralNavigationContractTests(unittest.TestCase):
    def setUp(self):
        self.template = (ROOT / "control/templates/control/gis/definitions.html").read_text()

    def test_four_screens_use_one_cascade_component(self):
        for marker in (
            'id="group-l1"', 'id="group-l2"', 'id="group-layer"',
            'id="standard-l1"', 'id="standard-catalog"', 'id="standard-layer"',
            'id="standard-field"', 'id="code-l1"', 'id="filter-catalog"',
            'id="filter-layer"', 'id="filter-field"', 'id="rule-l1"',
            'id="rule-l2"', 'id="rule-layer"', 'id="rule-field"',
        ):
            self.assertIn(marker, self.template)
        self.assertIn("const navigationConfig=", self.template)
        self.assertIn("function normalizeNavigation(key)", self.template)
        self.assertIn("function changeNavigation(key,level,value)", self.template)

    def test_cascade_resets_descendants_and_rejects_invalid_pairs(self):
        self.assertIn("navigationL2(state.l1)", self.template)
        self.assertIn("l2s.some(item=>item.id===state.l2)", self.template)
        self.assertIn("navigationLayers(state.l2)", self.template)
        self.assertIn("order.slice(order.indexOf(level)+1).forEach(name=>state[name]='')", self.template)
        for message in (
            "이 업무유형에 등록된 업무범위가 없습니다.",
            "이 업무범위에 연결된 레이어가 없습니다.",
            "선택한 레이어에 등록된 필드가 없습니다.",
        ):
            self.assertIn(message, self.template)

    def test_reload_context_is_ui_state_only(self):
        for marker in ("URLSearchParams(location.search)", "gis_tab", "history.replaceState", "sessionStorage"):
            self.assertIn(marker, self.template)
        definitions = (ROOT / "control/services/gis_definitions.py").read_text()
        self.assertIn("'catalog_navigation':category_tree(cur)", definitions)
        self.assertNotIn("l1_id", definitions)

    def test_photo_catalog_keeps_l3_and_uses_shared_l1_l2_tree(self):
        service = (ROOT / "control/services/gis_photo_policy.py").read_text()
        photo = (ROOT / "control/templates/control/gis/photo_catalog.html").read_text()
        self.assertIn("navigation = category_tree(cur)", service)
        self.assertIn('"lv3": lv3', service)
        for marker in ("photo-l1", "photo-l2", "photo-l3", "fillScopes"):
            self.assertIn(marker, photo)

    def test_no_schema_or_definition_mutation_added(self):
        service = (ROOT / "control/services/gis_catalog_navigation.py").read_text()
        self.assertNotIn("INSERT ", service)
        self.assertNotIn("UPDATE ", service)
        self.assertNotIn("DELETE ", service)
        self.assertNotIn("ALTER ", service)

    def test_deploy_compares_definition_row_counts(self):
        command = (ROOT / "control/management/commands/inspect_gis_definition_rows.py").read_text()
        workflow = (ROOT / ".github/workflows/gis-definition-code-deploy.yml").read_text()
        for table in (
            "definition_group", "definition_layer", "definition_layer_catalog",
            "definition_field", "definition_field_layer", "definition_code", "definition_rule",
        ):
            self.assertIn(f'"{table}"', command)
        self.assertIn("inspect_gis_definition_rows --write", workflow)
        self.assertIn("inspect_gis_definition_rows --compare", workflow)
        self.assertIn("gis_definition_row_counts_unchanged=yes", command)
        self.assertIn("gis_definition_relationship_fingerprints_unchanged=yes", command)


if __name__ == "__main__":
    unittest.main()
