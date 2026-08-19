from pathlib import Path

from django.test import SimpleTestCase

from geoflow_ops.forms import ContractForm
from geoflow_ops.process_workflow import default_stage_for_event
from geoflow_ops.services.tenant_settings import (
    _canonicalize_contract_status_labels,
    _merge_required_options,
)
from geoflow_ops.services.workflow_state import (
    _STAGE_ORDER,
    _stage_summary,
    event_affects_contract_lifecycle,
    major_phase_for_stage,
)


ROOT = Path(__file__).resolve().parent


class ContractLifecycleSemanticTests(SimpleTestCase):
    def test_major_lifecycle_is_contract_execution_closeout(self):
        self.assertEqual(major_phase_for_stage("contract"), ("contract", "계약"))
        self.assertEqual(major_phase_for_stage("kickoff"), ("execution", "진행"))
        self.assertEqual(major_phase_for_stage("execution"), ("execution", "진행"))
        self.assertEqual(major_phase_for_stage("inspection"), ("execution", "진행"))
        self.assertEqual(major_phase_for_stage("closeout"), ("closeout", "준공"))

    def test_billing_never_advances_technical_lifecycle(self):
        self.assertNotIn("billing", _STAGE_ORDER)
        self.assertFalse(event_affects_contract_lifecycle("billing", "invoice"))
        self.assertFalse(event_affects_contract_lifecycle("billing", "payment"))

    def test_contract_changes_do_not_move_lifecycle_backwards(self):
        for event_type in (
            "contract_change",
            "period_extension",
            "suspend",
            "resume",
        ):
            self.assertFalse(event_affects_contract_lifecycle("contract", event_type))

    def test_kickoff_and_closeout_are_lifecycle_milestones(self):
        self.assertTrue(event_affects_contract_lifecycle("kickoff", "kickoff"))
        self.assertTrue(event_affects_contract_lifecycle("execution", "progress_report"))
        self.assertTrue(event_affects_contract_lifecycle("inspection", "inspection_request"))
        self.assertTrue(event_affects_contract_lifecycle("closeout", "completion_doc"))
        self.assertTrue(event_affects_contract_lifecycle("closeout", "closeout_complete"))

    def test_closeout_progress_and_final_completion_are_visually_distinct(self):
        progress = _stage_summary("closeout", is_final_complete=False)
        final = _stage_summary("closeout", is_final_complete=True)

        self.assertEqual(progress["major_label"], "준공 진행")
        self.assertFalse(progress["is_final_complete"])
        self.assertEqual(final["major_label"], "✓ 준공완료")
        self.assertTrue(final["is_final_complete"])

    def test_legacy_cancel_status_remains_canceled_without_event_history(self):
        summary = _stage_summary(None, contract_status="cancel")
        self.assertEqual(summary["major_code"], "cancel")
        self.assertEqual(summary["major_label"], "취소")

    def test_explicit_closeout_completion_event_is_available(self):
        self.assertEqual(default_stage_for_event("closeout_complete"), "closeout")
        options = _merge_required_options(
            "event.type.closeout",
            [("completion_doc", "준공계")],
        )
        self.assertIn(("closeout_complete", "준공완료"), options)

    def test_contract_status_labels_match_lifecycle_language(self):
        rows = _canonicalize_contract_status_labels(
            [
                ("planned", "계약전"),
                ("active", "진행중"),
                ("complete", "완료"),
            ]
        )
        self.assertEqual(rows, [("planned", "계약"), ("active", "진행"), ("complete", "준공")])


class ContractLifecycleUiContractTests(SimpleTestCase):
    def test_contract_status_field_is_not_user_editable(self):
        self.assertTrue(ContractForm.base_fields["status"].disabled)

    def test_contract_list_uses_derived_lifecycle_and_fades_final_rows(self):
        source = (
            ROOT / "templates" / "geoflow_ops" / "contracts" / "contract_list.html"
        ).read_text(encoding="utf-8")
        self.assertIn('data-status="{{ wf.lifecycle_status }}"', source)
        self.assertIn("gf-contract-final", source)
        self.assertIn("opacity: .56", source)
        self.assertIn("gf-phase-closeout", source)
        self.assertNotIn("<th>운영상태</th>", source)

    def test_contract_detail_hides_legacy_manual_status_ui(self):
        source = (
            ROOT / "templates" / "geoflow_ops" / "base_tenant.html"
        ).read_text(encoding="utf-8")
        self.assertIn("statusSelect.disabled = true", source)
        self.assertIn("statusGroup.classList.add('d-none')", source)
        self.assertIn("text === '운영상태'", source)
        self.assertIn("label.textContent = '업무상태'", source)
        self.assertIn("lifecycle === '준공 진행'", source)
        self.assertIn("lifecycle.indexOf('준공완료')", source)

    def test_event_signal_recomputes_legacy_contract_status(self):
        source = (ROOT / "signals.py").read_text(encoding="utf-8")
        apps = (ROOT / "apps.py").read_text(encoding="utf-8")
        workflow = (ROOT / "services" / "workflow_state.py").read_text(encoding="utf-8")

        self.assertIn("@receiver(pre_save, sender=ProcessEvent)", source)
        self.assertIn("@receiver(post_save, sender=ProcessEvent)", source)
        self.assertIn("sync_contract_status_from_events", source)
        self.assertIn("from . import signals", apps)
        self.assertIn("UPDATE ctr.contracts", workflow)
        self.assertIn("if stage == \"billing\"", workflow)
        self.assertIn("has_lifecycle_event", workflow)
        self.assertIn("if stage not in _LIFECYCLE_STAGES", workflow)
