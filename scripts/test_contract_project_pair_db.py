"""Disposable PostgreSQL integration; fixed local test DB, no deployment settings."""
import sys
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from django.conf import settings
DB={'ENGINE':'django.db.backends.postgresql','NAME':'geoflow_policy_test','USER':'postgres',
    'PASSWORD':'postgres','HOST':'127.0.0.1','PORT':'5432','CONN_MAX_AGE':0}
settings.configure(SECRET_KEY='isolated-policy-test',INSTALLED_APPS=['django.contrib.auth','django.contrib.contenttypes','control','control.catalog','geoflow_ops'],DATABASES={'default':{'ENGINE':'django.db.backends.sqlite3','NAME':':memory:'},'tenant':DB},USE_TZ=True)
import django;django.setup()
from django.core.exceptions import ValidationError
from django.db import connections,transaction,DatabaseError
from geoflow_ops.models import Contract,Project
from geoflow_ops.services.contract_project_pair import create_project_for_new_contract,create_project,save_project,save_contract
from scripts.ops import activate_contract_project_policy as activation

DDL='''DROP SCHEMA IF EXISTS prj CASCADE; DROP SCHEMA IF EXISTS ctr CASCADE;
CREATE SCHEMA ctr; CREATE SCHEMA prj;
CREATE TABLE ctr.contracts(id uuid PRIMARY KEY,legacy_id bigint,code text UNIQUE,name text NOT NULL,
start_date date,end_date date,amount numeric(14,0),status text,kind text,division text,
client_id uuid,sub_client_id uuid,org_unit_id uuid,ext jsonb,created_at timestamptz,updated_at timestamptz,description text);
CREATE TABLE prj.projects(id uuid PRIMARY KEY,contract_id uuid REFERENCES ctr.contracts(id),code text UNIQUE,name text,
start_date date,end_date date,status text,description text,org_unit_id uuid,ext jsonb,created_at timestamptz,updated_at timestamptz);
'''

class PolicyTests(unittest.TestCase):
    def setUp(self):
        with connections['tenant'].cursor() as cur: cur.execute(DDL)
    def contract(self,mode='SINGLE',code='A-26'):
        return Contract.objects.using('tenant').create(code=code,name='Contract',amount=12345,ext={'project_mode':mode,'keep':'preserved'})
    def values(self,name='Project',status='active'):
        return dict(name=name,status=status,start_date=None,end_date=None,description='Note')
    def test_single_atomic_sync_and_reject_direct_name(self):
        with transaction.atomic(using='tenant'):
            c=self.contract();p=create_project_for_new_contract('tenant',c)
        self.assertEqual((p.name,p.code),('Contract','A-26-001'))
        c.name='Changed';save_contract('tenant',c,'SINGLE')
        p.refresh_from_db(using='tenant');self.assertEqual(p.name,'Changed')
        with self.assertRaises(ValidationError):save_project('tenant',p.pk,self.values('Bad'))
        self.assertEqual(Contract.objects.using('tenant').get(pk=c.pk).amount,12345)
        self.assertFalse(hasattr(p,'amount'))
    def test_multiple_modes_independent_and_confirmation(self):
        c=self.contract('MULTIPLE');self.assertIsNone(create_project_for_new_contract('tenant',c))
        a=create_project('tenant',c.pk,self.values('A','complete'))
        b=create_project('tenant',c.pk,self.values('B','pause'))
        c.name='Renamed';save_contract('tenant',c,'MULTIPLE')
        a.refresh_from_db(using='tenant');b.refresh_from_db(using='tenant')
        self.assertEqual((a.name,b.name,a.status,b.status),('A','B','complete','pause'))
        with self.assertRaises(ValidationError):save_contract('tenant',c,'SINGLE',confirm_single=True)
        Project.objects.using('tenant').filter(pk=b.pk).delete()
        with self.assertRaises(ValidationError):save_contract('tenant',c,'SINGLE')
        save_contract('tenant',c,'SINGLE',confirm_single=True)
        a.refresh_from_db(using='tenant');self.assertEqual(a.name,'Renamed')
    def test_sequence_survives_deletion_and_mode_change(self):
        c=self.contract();a=create_project_for_new_contract('tenant',c)
        save_contract('tenant',c,'MULTIPLE')
        b=create_project('tenant',c.pk,self.values('B'))
        self.assertEqual(b.code,'A-26-002')
        Project.objects.using('tenant').filter(pk=b.pk).delete()
        self.assertEqual(create_project('tenant',c.pk,self.values('C')).code,'A-26-003')
        c.refresh_from_db(using='tenant');self.assertEqual(c.ext['keep'],'preserved')
    def test_duplicate_warning_and_tenant_contract_lookup(self):
        c=self.contract('MULTIPLE');create_project('tenant',c.pk,self.values(' A  B '))
        with self.assertRaises(ValidationError):create_project('tenant',c.pk,self.values('a b'))
        create_project('tenant',c.pk,self.values('a b'),allow_duplicate=True)
        from uuid import uuid4
        with self.assertRaises(Contract.DoesNotExist):create_project('tenant',uuid4(),self.values())
        with self.assertRaises(ValueError):create_project('default',c.pk,self.values())
    def test_concurrent_single_and_multiple(self):
        for mode in ['SINGLE','MULTIPLE']:
            c=self.contract(mode,mode)
            barrier=threading.Barrier(2)
            def worker(i):
                try:
                    barrier.wait(timeout=10)
                    return create_project('tenant',c.pk,self.values(str(i))).code
                except ValidationError:return None
                finally:connections['tenant'].close()
            with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(worker,[1,2]))
            if mode=='SINGLE':self.assertEqual(sum(x is not None for x in result),1)
            else:self.assertEqual(set(result),{'MULTIPLE-001','MULTIPLE-002'})
    def test_insert_failure_rolls_back_contract_and_counter(self):
        with patch('geoflow_ops.services.contract_project_pair.Project.objects.using') as using:
            using.return_value.filter.return_value.exists.return_value=False
            using.return_value.filter.return_value.values_list.return_value=[]
            using.return_value.create.side_effect=DatabaseError('synthetic')
            with self.assertRaises(DatabaseError):
                with transaction.atomic(using='tenant'):
                    c=self.contract();create_project_for_new_contract('tenant',c)
        self.assertEqual(Contract.objects.using('tenant').count(),0)
    def test_policy_requires_explicit_mode(self):
        c=self.contract();c.ext={};c.save(using='tenant')
        with self.assertRaises(ValidationError):create_project('tenant',c.pk,self.values())
        with self.assertRaises(ValidationError):save_contract('tenant',c,'INVALID')
    def fixture(self):
        c=self.contract();c.ext={'keep':1};c.save(using='tenant')
        p=Project.objects.using('tenant').create(contract=c,name='Old',code='CA26',status='pause',ext={'gis':'untouched'})
        with connections['tenant'].cursor() as cur:
            rows=activation.read_rows(cur)
        after=[{**r,'project_name':r['contract_name'],'project_code':r['contract_code']+'-001'} for r in rows]
        target={'count':1,'before':activation.signature(rows),'after':activation.signature(after)}
        return c,p,rows,target
    def test_data_conversion_identity_ext_and_retry(self):
        c,p,rows,target=self.fixture()
        self.assertFalse(activation.validate(rows,target))
        with transaction.atomic(using='tenant'):
            activation.apply(connections['tenant'],rows,target)
        c.refresh_from_db(using='tenant');p.refresh_from_db(using='tenant')
        self.assertEqual((p.pk,p.contract_id,p.code,p.name,p.status,p.ext),(p.pk,c.pk,'A-26-001','Contract','pause',{'gis':'untouched'}))
        self.assertEqual(c.ext,{'keep':1,'project_mode':'SINGLE','project_sequence':1})
        with connections['tenant'].cursor() as cur:self.assertTrue(activation.validate(activation.read_rows(cur),target))
    def test_conversion_failure_rolls_back_both_tables(self):
        c,p,rows,target=self.fixture()
        with self.assertRaises(RuntimeError):
            with transaction.atomic(using='tenant'):
                activation.apply(connections['tenant'],rows,{**target,'after':'invalid'})
        c.refresh_from_db(using='tenant');p.refresh_from_db(using='tenant')
        self.assertEqual((c.ext,p.code,p.name),({'keep':1},'CA26','Old'))
    def test_prepare_checks_constraints_indexes_and_snapshot(self):
        c,p,rows,target=self.fixture()
        with transaction.atomic(using='tenant'):
            with connections['tenant'].cursor() as cur:
                cur.execute("""SELECT conrelid::regclass::text,conname,contype,pg_get_constraintdef(oid)
                    FROM pg_constraint WHERE conrelid IN ('ctr.contracts'::regclass,'prj.projects'::regclass)
                    OR confrelid IN ('ctr.contracts'::regclass,'prj.projects'::regclass)""")
                target['constraints']=activation.digest(sorted([list(r) for r in cur.fetchall()]))
                cur.execute("SELECT schemaname,tablename,indexname,indexdef FROM pg_indexes WHERE schemaname IN ('ctr','prj')")
                target['indexes']=activation.digest(sorted([list(r) for r in cur.fetchall()]))
            checked,done=activation.prepare(connections['tenant'],target)
            self.assertFalse(done);self.assertEqual(len(checked),1)
            with connections['tenant'].cursor() as cur:cur.execute('CREATE UNIQUE INDEX unexpected_code ON prj.projects(code,name)')
            with self.assertRaisesRegex(RuntimeError,'indexes_changed'):
                activation.prepare(connections['tenant'],target)

    def test_snapshot_and_relation_guard(self):
        c,p,rows,target=self.fixture()
        rows[0]['project_name']='concurrent edit'
        with self.assertRaises(RuntimeError):activation.validate(rows,target)
        with self.assertRaises(RuntimeError):activation.validate(rows*2,target)

if __name__=='__main__':unittest.main(verbosity=2)
