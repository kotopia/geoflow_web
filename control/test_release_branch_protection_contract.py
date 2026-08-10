from __future__ import annotations

from pathlib import Path
import re
import unittest


RELEASE_WORKFLOW = (
    Path(__file__).resolve().parent.parent
    / ".github"
    / "workflows"
    / "release-preflight.yml"
)


class ReleaseBranchProtectionContractTests(unittest.TestCase):
    def _source(self) -> str:
        return RELEASE_WORKFLOW.read_text(encoding="utf-8")

    def test_release_preflight_runs_for_every_release_pull_request(self):
        source = self._source()
        match = re.search(
            r"(?ms)^  pull_request:\n(?P<body>.*?)(?=^  [A-Za-z_][A-Za-z0-9_-]*:|\Z)",
            source,
        )
        self.assertIsNotNone(match, "release-preflight must define pull_request")
        body = match.group("body")
        self.assertIn("branches:", body)
        self.assertIn("- release/stabilized-deploy", body)
        self.assertNotIn(
            "paths:",
            body,
            "required release checks must not be skipped by pull_request path filters",
        )
        self.assertNotIn(
            "paths-ignore:",
            body,
            "required release checks must not be skipped by pull_request path filters",
        )

    def test_required_status_check_job_ids_remain_stable(self):
        source = self._source()
        required_job_ids = (
            "release-preflight",
            "migration-rehearsal",
            "public-https-smoke",
        )
        for job_id in required_job_ids:
            self.assertRegex(
                source,
                rf"(?m)^  {re.escape(job_id)}:\s*$",
                f"required status-check job id changed or disappeared: {job_id}",
            )

    def test_release_workflow_has_no_production_environment_gate(self):
        source = self._source()
        self.assertNotIn(
            "environment: production",
            source,
            "PR-required checks must never wait on production approval",
        )


if __name__ == "__main__":
    unittest.main()
