from pathlib import Path

from django.test import SimpleTestCase

ROOT = Path(__file__).resolve().parent


def source(path):
    return (ROOT / path).read_text(encoding="utf-8")


class ListEventBadgeAndProjectContractParityTests(SimpleTestCase):
    def test_contract_events_and_project_performance_remain_separate(self):
        contract_list = source("templates/geoflow_ops/contracts/contract_list.html")
        project_list = source("templates/geoflow_ops/projects/project_list.html")
        workflow_tags = source("templatetags/workflow_tags.py")
        helper = source("services/active_event_badges.py")

        self.assertIn("wf.active_event_labels", contract_list)
        self.assertNotIn("{% contract_workflow p.contract as wf %}", project_list)
        self.assertIn("p.status_label", project_list)
        self.assertIn("active_event_summaries_for_contracts", workflow_tags)
        self.assertIn('Q(scope_type="contract", scope_id__in=ids)', helper)
        self.assertIn('Q(scope_type="project", scope_id__in=project_ids)', helper)
        self.assertIn("project_to_contract", helper)

    def test_project_detail_keeps_independent_facts_after_page_load(self):
        base = source("templates/geoflow_ops/base_tenant.html")
        detail = source("templates/geoflow_ops/projects/project_detail.html")
        self.assertNotIn("project-contract-card-parity.js", base)
        for field in ("obj.name", "obj.code", "obj.start_date", "obj.end_date", "obj.status_label", "obj.contract.name"):
            self.assertIn(field, detail)
