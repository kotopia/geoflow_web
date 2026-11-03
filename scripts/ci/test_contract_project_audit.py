import copy
import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('audit', ROOT / 'scripts/ops/audit_contract_projects.py')
audit = importlib.util.module_from_spec(spec)
spec.loader.exec_module(audit)


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.contracts = [{'id':'c1','code':'A-2026','name':'Contract','ext':{'keep':1}}]
        self.projects = [{'id':'p1','contract_id':'c1','code':'CA2026','name':'Contract','status':'active'}]

    def test_exact_legacy_rule_and_uuid_preservation(self):
        before = copy.deepcopy((self.contracts, self.projects))
        r = audit.analyze(self.contracts, self.projects)
        self.assertEqual(r['blockers'], [])
        self.assertEqual(r['changes'][0]['after_code'], 'A-2026-001')
        self.assertTrue(r['changes'][0]['legacy_automatic_code'])
        self.assertEqual(r['changes'][0]['project_id'], 'p1')
        self.assertEqual((self.contracts, self.projects), before)

    def test_already_converted_is_no_code_change(self):
        self.projects[0]['code'] = 'A-2026-001'
        self.assertEqual(audit.analyze(self.contracts,self.projects)['counts']['code_changes'],0)

    def test_c_prefix_is_not_stripped_blindly(self):
        self.projects[0]['code'] = 'CUSTOM'
        self.assertIn('unrecognized_project_code_requires_review', audit.analyze(self.contracts,self.projects)['blockers'])

    def test_name_mismatch_requires_semantic_review(self):
        self.projects[0]['name'] = 'Independent work'
        r = audit.analyze(self.contracts,self.projects)
        self.assertEqual(r['counts']['name_mismatches'],1)
        self.assertIn('name_changes_require_semantic_review',r['blockers'])

    def test_multiple_and_orphan_not_proposed(self):
        self.projects += [dict(self.projects[0],id='p2'),dict(self.projects[0],id='p3',contract_id=None)]
        r = audit.analyze(self.contracts,self.projects)
        self.assertEqual(r['changes'],[])
        self.assertEqual(r['counts']['multiple_project_contracts'],1)
        self.assertEqual(r['counts']['orphan_projects'],1)

    def test_zero_project_requires_review(self):
        self.assertIn('contracts_without_project_require_review',audit.analyze(self.contracts,[])['blockers'])

    def test_target_code_collision(self):
        self.projects.append(dict(self.projects[0],id='p2',contract_id=None,code='A-2026-001'))
        self.assertIn('proposed_code_collision',audit.analyze(self.contracts,self.projects)['blockers'])

    def test_ext_and_missing_code_fail_closed(self):
        for ext in ([], 'text', 1):
            self.contracts[0]['ext']=ext
            self.assertIn('non_object_contract_ext',audit.analyze(self.contracts,self.projects)['blockers'])
        self.contracts[0]['ext']={'project_mode':'MULTIPLE'}
        self.contracts[0]['code']=''
        r=audit.analyze(self.contracts,self.projects)
        self.assertIn('existing_project_mode_requires_review',r['blockers'])
        self.assertIn('missing_or_untrimmed_contract_code',r['blockers'])

    def test_workflow_preserves_gate_and_encrypts_details(self):
        workflow=(ROOT/'.github/workflows/contract-project-policy-audit.yml').read_text()
        self.assertIn('environment: production',workflow)
        self.assertIn("github.event_name != 'pull_request'",workflow)
        self.assertIn('StrictHostKeyChecking=yes',workflow)
        self.assertIn('openssl cms -encrypt',workflow)
        self.assertIn('path: ${{ runner.temp }}/contract-project-audit.cms',workflow)
        self.assertNotIn('cat "$report"',workflow)
        source=(ROOT/'scripts/ops/audit_contract_projects.py').read_text()
        self.assertIn('SET TRANSACTION READ ONLY',source)
        self.assertIn("readonly=True, isolation_level='REPEATABLE READ'",source)
        self.assertNotIn('.commit(',source)


if __name__=='__main__':
    unittest.main()
