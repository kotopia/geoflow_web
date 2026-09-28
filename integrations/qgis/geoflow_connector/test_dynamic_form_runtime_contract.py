# 제목: QGIS Dynamic Form 런타임 구조 테스트
# 기능: 공통 위젯·스타일·중앙 전용 실행 경로와 패키지 리소스를 점검
from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parent


class DynamicRuntimeContractTests(unittest.TestCase):
    def test_112_shell_and_resources_are_packaged(self):
        for path in ("app/unified.py", "app/protection.py", "app/state.py", "ui/form_host.py",
                     "ui/form_header.py", "ui/presentation.py", "ui/designer/main_dock.ui",
                     "ui/designer/layer_workspace.ui", "resources/feather.qrc",
                     "resources/feather_rc.py", "resources/qt_resources.py",
                     "resources/styles/geoflow_form.qss", "forms/dynamic/style.py"):
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

    def test_dynamic_widgets_use_one_shared_geoflow_style(self):
        widgets = (ROOT / "forms/dynamic/widgets.py").read_text(encoding="utf-8")
        layout = (ROOT / "forms/dynamic/layout.py").read_text(encoding="utf-8")
        form = (ROOT / "forms/dynamic/form.py").read_text(encoding="utf-8")
        qss = (ROOT / "resources/styles/geoflow_form.qss").read_text(encoding="utf-8")

        for name in ("GeoFlowLineEdit", "GeoFlowTextEdit", "GeoFlowComboBox",
                     "GeoFlowSpinBox", "GeoFlowDoubleSpinBox", "GeoFlowCheckBox",
                     "GeoFlowDateEdit", "GeoFlowDateTimeEdit"):
            self.assertIn("class " + name, widgets)
        self.assertNotIn("setStyleSheet", widgets)
        self.assertIn("apply_form_style(self)", form)
        self.assertIn('geoflowRole", "fieldLabel', layout)
        self.assertIn('geoflowRole", "fieldError', layout)
        self.assertIn("attach_error_label", layout)
        self.assertIn("def showPopup(self):", widgets)
        self.assertLess(widgets.index("isinstance(widget, QDateTimeEdit)"),
                        widgets.index("isinstance(widget, QDateEdit)"))

        for state in ('[error="true"]', '[readonly="true"]', ":disabled",
                      ":hover", ":focus"):
            self.assertIn(state, qss)
        for resource in ("chevron-down.svg", "chevron-up.svg", "calendar.svg",
                         "check.svg"):
            self.assertIn(":/geoflow/feather/" + resource, qss)

    def test_main_navigation_uses_one_scoped_shared_style(self):
        qss_path = ROOT / "resources/styles/geoflow_main.qss"
        helper = (ROOT / "ui/main_style.py").read_text(encoding="utf-8")
        dialog = (ROOT / "ui/dialog.py").read_text(encoding="utf-8")
        workspace = (ROOT / "ui/layer_workspace.py").read_text(encoding="utf-8")
        qss = qss_path.read_text(encoding="utf-8")

        self.assertTrue(qss_path.is_file())
        self.assertIn('setProperty("geoflowMain", True)', helper)
        self.assertIn("geoflow_main.qss", helper)
        self.assertIn("apply_main_style(self.project_panel)", dialog)
        self.assertIn("apply_main_style(self)", workspace)
        self.assertIn('[geoflowMain="true"]', qss)

    def test_validation_feedback_preserves_rule_validation_result(self):
        form = (ROOT / "forms/dynamic/form.py").read_text(encoding="utf-8")
        self.assertIn("errors = validate(self.definition, self.fields, self.values())", form)
        self.assertIn("return errors", form)

    def test_local_layout_is_qsettings_only_and_shutdown_host_does_not_reopen(self):
        editor = (ROOT / "forms/dynamic/layout_editor.py").read_text(encoding="utf-8")
        model = (ROOT / "forms/dynamic/layout_model.py").read_text(encoding="utf-8")
        renderer = (ROOT / "forms/dynamic/layout.py").read_text(encoding="utf-8")
        host = (ROOT / "ui/form_host.py").read_text(encoding="utf-8")

        self.assertIn('KEY_PREFIX = "GeoFlowConnector/formLayouts/"', editor)
        self.assertIn("QSettings", editor)
        self.assertNotIn("client.", editor)
        self.assertNotIn("definition_field", editor + model)
        self.assertIn("미배치 필드", model)
        self.assertIn("QHBoxLayout", renderer)
        self.assertIn("page.dirty and not self._shutting_down", host)
        shutdown = host.split("def shutdown(self):", 1)[1]
        self.assertNotIn("self.show_retained()", shutdown)

    def test_recovery_approval_allows_the_original_close_event(self):
        unified = (ROOT / "app/unified.py").read_text(encoding="utf-8")
        self.assertIn("if self._approved:", unified)
        self.assertIn("event.accept()", unified)
        self.assertIn("복구 JSON을 저장하지 못해 전환을 중단했습니다.", unified)
        protection = (ROOT / "app/protection.py").read_text(encoding="utf-8")
        self.assertIn("getattr(page, 'layer_id', '')", protection)
        host = (ROOT / "ui/form_host.py").read_text(encoding="utf-8")
        self.assertIn("저장 후 종료", host)
        self.assertIn("변경 취소 후 종료", host)
        self.assertIn("종료 취소", host)


if __name__ == "__main__":
    unittest.main()
