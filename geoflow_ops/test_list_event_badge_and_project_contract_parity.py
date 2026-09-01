from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


class ListEventBadgeAndProjectContractParityTests(SimpleTestCase):
    def test_contract_and_project_lists_render_stage_plus_active_event_badges(self):
        contract_list = source("templates/geoflow_ops/contracts/contract_list.html")
        project_list = source("templates/geoflow_ops/projects/project_list.html")
        workflow_tags = source("templatetags/workflow_tags.py")
        helper = source("services/active_event_badges.py")

        self.assertIn("wf.active_event_labels", contract_list)
        self.assertIn("{% contract_workflow p.contract as wf %}", project_list)
        self.assertIn("wf.active_event_labels", project_list)
        self.assertIn("active_event_labels_for_contracts", workflow_tags)
        self.assertIn('Q(scope_type="contract", scope_id__in=ids)', helper)
        self.assertIn('Q(scope_type="project", scope_id__in=project_ids)', helper)
        self.assertIn("project_to_contract", helper)

    def test_project_contract_information_uses_contract_detail_row_design(self):
        base = source("templates/geoflow_ops/base_tenant.html")
        parity = source("static/geoflow_ops/js/project-contract-card-parity.js")

        self.assertIn("project-contract-card-parity.js", base)
        self.assertIn("card-header", parity)
        self.assertIn("card-title mb-0\">계약정보", parity)
        self.assertIn("row py-2 border-top", parity)
        self.assertIn("col-sm-4 col-lg-3 small text-muted", parity)
        self.assertIn("col-sm-8 col-lg-9", parity)
        self.assertIn("현재 업무단계", parity)
        self.assertIn("계약기간", parity)
