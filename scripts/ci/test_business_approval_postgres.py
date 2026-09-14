"""Focused approval-guard checks; explicit disposable DB opt-in required."""
import copy
import importlib.util
import json
import hashlib
import tempfile
import unittest
import sys
import os
import subprocess
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT))
from geoflow_ops.gis import business_approval as guard
from geoflow_ops.gis.business_fields import inspect_contract, plan_contract


class ApprovalGuardTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        spec=importlib.util.spec_from_file_location('approval_fixture',Path(__file__).with_name('business_approval_fixture.py'))
        fixture=importlib.util.module_from_spec(spec);spec.loader.exec_module(fixture)
        cls.fixture=fixture;cls.conn=fixture.conn;cls.cur=fixture.cur;cls.project=fixture.project
        cls.context=dict(database=fixture.DB,group_code='fixture-only',db_alias='fixture-only',project_code='26003',project_id=cls.project)
        cls.approval=guard.build_approval(cls.cur,cls.project,cls.context)
        cls.conn.rollback()

    @classmethod
    def tearDownClass(cls):cls.conn.close()

    def setUp(self):self.writes=[]
    def tearDown(self):self.conn.rollback()

    def proxy(self):
        owner=self
        class Cursor:
            def execute(self,sql,parameters=None):
                if sql.startswith(('UPDATE ','INSERT ','DELETE ','ALTER ','DROP ','CREATE ')):owner.writes.append(sql)
                return owner.cur.execute(sql,parameters)
            def __getattr__(self,name):return getattr(owner.cur,name)
        return Cursor()

    def run_guard(self,**kw):return guard.guarded_reconcile(self.proxy(),self.project,self.approval,self.context,**kw)

    def assert_rejected_without_writes(self):
        with self.assertRaises(guard.ApprovalRejected):self.run_guard()
        self.assertEqual(self.writes,[])

    def test_exact_transition_and_new_uuid_independent_noop(self):
        self.assertEqual(self.run_guard(),72);self.assertEqual(len(self.writes),72)
        self.writes=[];self.assertEqual(self.run_guard(),0);self.assertEqual(self.writes,[])

    def test_same_count_changed_field_name_is_rejected(self):
        self.cur.execute("UPDATE gis.meta_field_def SET physical_name='different_removed_target' WHERE id=%s",[self.fixture.uid('wtl_etc_ps/fixture_removed_0')])
        self.assertEqual(len(plan_contract(inspect_contract(self.cur,self.project))),72)
        self.assert_rejected_without_writes()

    def test_same_count_changed_before_value_is_rejected(self):
        self.cur.execute("UPDATE gis.meta_field_def SET label='different before value' WHERE id=%s",[self.fixture.uid('wtl_pipe_lm/ist_ymd')])
        self.assertEqual(len(plan_contract(inspect_contract(self.cur,self.project))),72)
        self.assert_rejected_without_writes()

    def test_existing_profile_link_id_change_rejected(self):
        self.cur.execute('UPDATE gis.profile_field SET id=%s WHERE id=%s',[self.fixture.uid('replacement-link'),self.approval['before']['links'][0]['id']])
        self.assert_rejected_without_writes()

    def test_existing_permission_drift_rejected(self):
        self.cur.execute('UPDATE gis.profile_field SET editable=NOT editable WHERE id=%s',[self.approval['before']['links'][0]['id']])
        self.assert_rejected_without_writes()

    def test_partial_application_rejected(self):
        self.cur.execute('UPDATE gis.profile_field SET enabled=false WHERE profile_id=%s AND field_def_id=%s',
                         [self.fixture.selected,self.fixture.uid('wtl_etc_ps/fixture_removed_0')])
        self.assert_rejected_without_writes()

    def test_same_count_changed_planned_value_rejected(self):
        actual=plan_contract
        def changed(state):
            ops=actual(state)
            for i,(sql,values) in enumerate(ops):
                if sql==guard.SQL['field_update']:
                    values=list(values);values[2]='unapproved after label';ops[i]=(sql,values);break
            return ops
        with patch.object(guard,'plan_contract',changed):self.assert_rejected_without_writes()

    def test_forbidden_sql_rejected_before_any_write(self):
        for forbidden in ('ALTER TABLE gis.wtl_pipe_lm ADD forbidden text','DELETE FROM gis.profile_field','UPDATE gis.ref_code_value SET label=%s','UPDATE gis.wtl_pipe_lm SET status=%s'):
            def changed(state,sql=forbidden):
                ops=plan_contract(state);ops[-1]=(sql,[]);return ops
            with self.subTest(sql=forbidden),patch.object(guard,'plan_contract',changed):self.assert_rejected_without_writes()

    def test_post_state_permission_drift_even_with_zero_plan_rejected(self):
        self.assertEqual(self.run_guard(),72);self.writes=[]
        self.cur.execute("UPDATE gis.profile_field SET visible=false WHERE profile_id=%s AND field_def_id IN (SELECT id FROM gis.meta_field_def WHERE physical_name='worker_id')",[self.fixture.selected])
        self.assertEqual(plan_contract(inspect_contract(self.cur,self.project)),[])
        self.assert_rejected_without_writes()

    def test_noop_precheck_race_cannot_write_without_backup(self):
        with self.assertRaises(guard.ApprovalRejected):self.run_guard(allow_changes=False)
        self.assertEqual(self.writes,[])

    def test_hash_mismatch_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            p=Path(tmp)/'approval.json';p.write_text(json.dumps(self.approval),encoding='utf-8')
            expected=hashlib.sha256(p.read_bytes()).hexdigest()
            self.assertEqual(guard.load_approval(p,expected),self.approval)
            with self.assertRaises(guard.ApprovalRejected):guard.load_approval(p,'0'*64)

    def test_post_verification_failure_rolls_back_transaction(self):
        real=guard.normalize_inserted_ids;calls=0
        def mismatched(*args):
            nonlocal calls
            calls+=1
            return {} if calls==2 else real(*args)
        with patch.object(guard,'normalize_inserted_ids',mismatched):
            with self.assertRaises(guard.ApprovalRejected):self.run_guard()
        self.assertEqual(len(self.writes),72)
        self.conn.rollback()
        state=inspect_contract(self.cur,self.project)
        self.assertEqual(guard.snapshot(self.cur,state),self.approval['before'])

    def messages_fixture(self):
        from geoflow_ops.gis.business_fields import TABLES
        reports={'00_database':{'database':self.context['database']},
          '01_project_identity':dict(verified=True,cached_uuid=self.project,expected_code='26003'),
          '04_effective_profile':{'profile_id':self.fixture.selected},
          '99_completed':{'readonly_queries_finished':True}}
        for table in TABLES:
            ft=self.fixture.uid(table)
            reports['10_table_state.'+table]={'feature_metadata':[dict(id=ft,active=True)]}
            rows=[]
            for r in self.approval['before']['fields']:
                if r['feature_type_id']!=ft:continue
                rows.append(dict(field_id=r['id'],field=r['physical_name'],type=r['data_type'],group_key=r['code_group_key'],widget=r['widget_type'],
                    physical_missing=r['physical_name'].startswith('fixture_removed_') or r['physical_name'] in ('ist_ymd','sys_chk'),
                    profile_links=[{k:p[k] for k in ('profile_id','enabled','required','editable','visible','sort_order')} for p in self.approval['before']['links'] if p['field_def_id']==r['id']]))
            reports['14_metadata_and_shared_links.'+table]=rows
        return reports

    def test_original_messages_id_crosscheck(self):
        from geoflow_ops.gis.business_messages import verify_messages
        reports=self.messages_fixture()
        raw=('\n'.join('NOTICE:  '+k+': '+json.dumps(v) for k,v in reports.items())).encode()
        result=verify_messages(raw,self.approval)
        self.assertEqual(len(result['disabled_fields']),31)
        self.assertEqual(result['matched_existing_fields'],51)

    def test_messages_same_count_wrong_id_and_incomplete_rejected(self):
        from geoflow_ops.gis.business_messages import verify_messages
        for mismatch in ('id','incomplete','settings'):
            reports=self.messages_fixture()
            row=reports['14_metadata_and_shared_links.wtl_pipe_lm'][0]
            if mismatch=='id':row['field_id']=self.fixture.uid('wrong-message-id')
            elif mismatch=='incomplete':del reports['99_completed']
            else:row['profile_links'][0]['editable']=True
            raw=('\n'.join('NOTICE:  '+k+': '+json.dumps(v) for k,v in reports.items())).encode()
            with self.subTest(mismatch=mismatch),self.assertRaises(guard.ApprovalRejected):verify_messages(raw,self.approval)

    def test_cli_cannot_apply_without_reviewed_file_and_digest(self):
        env=dict(os.environ,PYTHONPATH=str(ROOT))
        result=subprocess.run([sys.executable,str(ROOT/'scripts/ops/reconcile_gis_business_fields.py'),
            '--group-code','cheonan','--db-alias','cheonan_db','--project-id',self.project,'--apply'],
            env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('independently reviewed',result.stderr)

    def test_cli_cannot_export_approval_without_original_messages(self):
        env=dict(os.environ,PYTHONPATH=str(ROOT))
        result=subprocess.run([sys.executable,str(ROOT/'scripts/ops/reconcile_gis_business_fields.py'),
            '--group-code','cheonan','--db-alias','cheonan_db','--project-id',self.project,
            '--export-approval','must-not-be-created.json'],env=env,capture_output=True,text=True)
        self.assertEqual(result.returncode,2)
        self.assertIn('original --messages-file',result.stderr)


class BackupCredentialTests(unittest.TestCase):
    def setUp(self):
        from unittest.mock import Mock
        self.Mock = Mock
        sys.path.insert(0,str(ROOT/'scripts/ops'))
        spec=importlib.util.spec_from_file_location('backup_cli',ROOT/'scripts/ops/reconcile_gis_business_fields.py')
        self.cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(self.cli)

    def test_masked_dsn_uses_resolver_only_in_child_environment(self):
        from types import SimpleNamespace
        resolver=self.Mock()
        resolver.is_tenant_db_secret_reference.return_value=True
        resolver.resolve_tenant_db_password.return_value='test-only-resolved-password'
        connection=SimpleNamespace(dsn='dbname=testdb host=testhost port=5433 user=testuser password=xxx sslmode=require')
        before=dict(os.environ)
        with patch.dict(sys.modules,{'control.services.tenant_db_secret_resolver':resolver}):
            env=self.cli._backup_environment(SimpleNamespace(db_password='test-secret-reference'),connection)
        self.assertEqual(env['PGPASSWORD'],'test-only-resolved-password')
        self.assertEqual({k:env[k] for k in ('PGDATABASE','PGHOST','PGPORT','PGUSER','PGSSLMODE')},
                         dict(PGDATABASE='testdb',PGHOST='testhost',PGPORT='5433',PGUSER='testuser',PGSSLMODE='require'))
        resolver.resolve_tenant_db_password.assert_called_once_with('test-secret-reference')
        self.assertEqual(dict(os.environ),before)

    def test_failed_backup_never_calls_guard_or_commits(self):
        from contextlib import ExitStack,redirect_stdout
        from types import SimpleNamespace
        from unittest.mock import MagicMock
        import io
        conn=MagicMock()
        args=['tool','--group-code','fixture','--db-alias','fixture','--project-id',
              '86f52715-3cca-4124-9cc6-cb7c6a7e9c4e','--apply','--approval-file','fixture.json','--approval-sha256','0'*64]
        with tempfile.TemporaryDirectory() as tmp,ExitStack() as stack:
            stack.enter_context(patch.object(sys,'argv',args+['--backup-dir',tmp]))
            stack.enter_context(patch.object(self.cli,'_locate',return_value=SimpleNamespace(db_name='fixture')))
            stack.enter_context(patch.object(self.cli,'_connect_tenant',return_value=conn))
            stack.enter_context(patch.object(self.cli,'_backup_environment',return_value={'PGPASSWORD':'test-only-child-password'}))
            stack.enter_context(patch.object(guard,'load_approval',return_value={'evidence':{'verified':True}}))
            stack.enter_context(patch('geoflow_ops.gis.business_fields.inspect_contract',return_value={'profile':'fixture'}))
            stack.enter_context(patch('geoflow_ops.gis.business_fields.plan_contract',return_value=[('fixture',[])]))
            apply=stack.enter_context(patch.object(guard,'guarded_reconcile'))
            run=stack.enter_context(patch.object(self.cli.subprocess,'run',return_value=SimpleNamespace(returncode=1,stderr=b'failure')))
            output=io.StringIO()
            with redirect_stdout(output),self.assertRaisesRegex(RuntimeError,'Backup failed'):
                self.cli.main()
            apply.assert_not_called();conn.commit.assert_not_called();conn.close.assert_called_once()
            self.assertNotIn('test-only-child-password',output.getvalue())
            self.assertNotIn('test-only-child-password',str(run.call_args.args))


if __name__=='__main__':unittest.main()
