"""Validate new protected path without running deployment commands."""
from pathlib import Path
import shutil
import subprocess
import unittest
import yaml

ROOT=Path(__file__).resolve().parents[2]
FILE=ROOT/'.github/workflows/gis-business-contract-code-deploy.yml'


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.source=FILE.read_text(encoding='utf-8')
        self.workflow=yaml.load(self.source,Loader=yaml.BaseLoader)
        self.job=self.workflow['jobs']['deploy-current-release']

    def test_manual_dispatch_retains_production_and_exact_sha_gates(self):
        self.assertEqual(set(self.workflow['on']),{'workflow_dispatch'})
        self.assertEqual(self.job['environment'],'production')
        self.assertEqual(self.workflow['permissions'],{'contents':'read'})
        self.assertIn('release/stabilized-deploy',self.job['if'])
        self.assertIn('test "$APPROVED_SHA" = "$GITHUB_SHA"',self.source)
        self.assertIn('candidate_not_current_release_head',self.source)
        self.assertIn('StrictHostKeyChecking=yes',self.source)
        self.assertIn('production_worktree_dirty',self.source)
        self.assertIn('trap on_exit EXIT',self.source)

    def test_no_database_activation_or_dependency_static_side_effects(self):
        for forbidden in ('cur.execute(', 'run_tenant(', 'manage.py migrate', 'collectstatic', 'pip install', '--apply', 'migrate_all_tenants'):
            self.assertNotIn(forbidden,self.source)
        self.assertIn('changed_path_outside_gis_code_contract',self.source)
        self.assertNotIn('geoflow_ops/gis/*',self.source)
        self.assertIn('default_transaction_read_only=on',self.source)

    def test_every_shell_block_parses_without_execution(self):
        bash=shutil.which('bash')
        if not bash:
            fallback=Path('C:/Program Files/Git/bin/bash.exe')
            if fallback.is_file():bash=str(fallback)
        if not bash:self.fail('bash required to validate deployment script syntax')
        for step in self.job['steps']:
            if 'run' in step:
                result=subprocess.run([bash,'-n'],input=step['run'],text=True,capture_output=True)
                self.assertEqual(result.returncode,0,result.stderr)


if __name__=='__main__':unittest.main()
