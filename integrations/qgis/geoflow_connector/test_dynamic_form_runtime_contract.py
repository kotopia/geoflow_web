from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class DynamicRuntimeContractTests(unittest.TestCase):
    def test_112_shell_and_resources_are_packaged(self):
        for path in ("app/unified.py", "app/protection.py", "app/state.py", "ui/form_host.py",
                     "ui/form_header.py", "ui/presentation.py", "ui/designer/main_dock.ui",
                     "ui/designer/layer_workspace.ui", "resources/feather.qrc",
                     "resources/feather_rc.py", "resources/qt_resources.py"):
            self.assertTrue((ROOT / path).is_file(), path)
        self.assertGreaterEqual(len(list((ROOT / "resources/icons").rglob("*"))), 300)

    def test_runtime_has_no_layer_specific_form_registry_or_maps(self):
        runtime = [path for path in ROOT.rglob("*.py") if not path.name.startswith("test_")]
        source = "\n".join(path.read_text(encoding="utf-8") for path in runtime)
        for forbidden in ("FIELD_MAPS", "CODE_GROUPS", "forms.registry", "forms.water"):
            self.assertNotIn(forbidden, source)
        self.assertFalse((ROOT / "forms/water").exists())

    def test_dynamic_components_and_central_fail_closed_contract_exist(self):
        host = (ROOT / "ui/form_host.py").read_text(encoding="utf-8")
        definition = (ROOT / "api/definitions.py").read_text(encoding="utf-8")
        self.assertIn("DynamicForm", host)
        self.assertIn("DynamicFormBinding", host)
        self.assertIn("form_definition_url", definition)
        self.assertIn("definition_revision_mismatch", definition)
        self.assertNotIn("tenant", definition.casefold())


if __name__ == "__main__":
    unittest.main()
