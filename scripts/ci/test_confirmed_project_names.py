import importlib.util
import os
from pathlib import Path
import unittest
from uuid import UUID

ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location('repair', ROOT/'scripts/ops/repair_confirmed_project_names.py')
repair = importlib.util.module_from_spec(spec)
spec.loader.exec_module(repair)


def fixtures():
    rows = [dict(contract_id=str(UUID(int=i)), project_id=str(UUID(int=i+10)),
                 contract_code=f'C{i}', contract_name=f'Correct {i}', project_code=f'P{i}',
                 project_name=f'Old {i}', project_count=1) for i in range(1,5)]
    manifest = {'group_sha256':repair.digest('tenant-a'), 'targets':[]}
    for row in rows:
        after = dict(row, project_name=row['contract_name'])
        manifest['targets'].append({'identity':repair.identity('tenant-a',row['contract_id'],row['project_id']),
                                    'before':repair.state(row), 'after':repair.state(after)})
    return rows, manifest


class GuardTests(unittest.TestCase):
    def test_exact_targets_and_idempotence(self):
        rows, manifest = fixtures()
        self.assertEqual(sum(done for _,_,done in repair.select_targets(rows,'tenant-a',manifest)),0)
        for row in rows: row['project_name']=row['contract_name']
        self.assertTrue(all(done for _,_,done in repair.select_targets(rows,'tenant-a',manifest)))

    def test_different_tenant_fails(self):
        rows, manifest=fixtures()
        with self.assertRaises(RuntimeError): repair.select_targets(rows,'tenant-b',manifest)

    def test_stale_name_code_or_relationship_fails(self):
        for key,value in [('contract_name','New change'),('project_name','New change'),
                          ('project_code','changed'),('contract_code','changed'),
                          ('project_count',2),('contract_id',str(UUID(int=99)))]:
            rows,manifest=fixtures();rows[0][key]=value
            with self.subTest(key=key),self.assertRaises(RuntimeError):
                repair.select_targets(rows,'tenant-a',manifest)

    def test_incomplete_or_duplicate_manifest_fails(self):
        rows,manifest=fixtures()
        for targets in (manifest['targets'][:3], [manifest['targets'][0]]*4):
            with self.assertRaises(RuntimeError):
                repair.select_targets(rows,'tenant-a',dict(manifest,targets=targets))


@unittest.skipUnless(os.environ.get('NAME_REPAIR_TEST_DB')=='1', 'disposable PostgreSQL only')
class DatabaseTests(unittest.TestCase):
    def setUp(self):
        import psycopg2
        self.conn=psycopg2.connect(host='127.0.0.1',port=5432,user='postgres',password='postgres',
                                dbname='geoflow_name_repair_test')
        self.addCleanup(self.conn.close)
        self.rows,self.manifest=fixtures()
        with self.conn.cursor() as c:
            c.execute('DROP SCHEMA IF EXISTS prj CASCADE; DROP SCHEMA IF EXISTS ctr CASCADE')
            c.execute('CREATE SCHEMA ctr; CREATE SCHEMA prj')
            c.execute('CREATE TABLE ctr.contracts(id uuid PRIMARY KEY,code text,name text)')
            c.execute('''CREATE TABLE prj.projects(id uuid PRIMARY KEY,contract_id uuid REFERENCES ctr.contracts,
                code text UNIQUE,name text,updated_at timestamptz,status text DEFAULT 'active',
                ext jsonb DEFAULT '{"keep":true}')''')
            for r in self.rows:
                c.execute('INSERT INTO ctr.contracts VALUES (%s,%s,%s)',
                          (r['contract_id'],r['contract_code'],r['contract_name']))
                c.execute('INSERT INTO prj.projects(id,contract_id,code,name) VALUES (%s,%s,%s,%s)',
                          (r['project_id'],r['contract_id'],r['project_code'],r['project_name']))
            c.execute("INSERT INTO ctr.contracts VALUES (%s,'other','Unrelated')",(str(UUID(int=999)),))
            c.execute("INSERT INTO prj.projects(id,contract_id,code,name) VALUES (%s,%s,'other','Preserve')",
                      (str(UUID(int=998)),str(UUID(int=999))))
        self.conn.commit()

    def names(self):
        with self.conn.cursor() as c:
            c.execute('SELECT name FROM prj.projects ORDER BY id')
            values=[r[0] for r in c.fetchall()]
        self.conn.rollback()
        return values

    def test_commit_preservation_backup_and_replay(self):
        backups=[]
        result=repair.repair(self.conn,'tenant-a',self.manifest,backups.append)
        self.assertEqual(result['updated'],4)
        self.assertEqual(len(backups),1)
        self.assertEqual([r['project_name'] for r in backups[0]['targets']], [f'Old {i}' for i in range(1,5)])
        self.assertEqual(self.names(),[f'Correct {i}' for i in range(1,5)]+['Preserve'])
        result=repair.repair(self.conn,'tenant-a',self.manifest,backups.append)
        self.assertEqual(result['updated'],0)
        self.assertEqual(len(backups),1)

    def test_backup_failure_prevents_all_writes(self):
        def fail(_): raise OSError('backup unavailable')
        with self.assertRaises(OSError): repair.repair(self.conn,'tenant-a',self.manifest,fail)
        self.assertEqual(self.names(),[f'Old {i}' for i in range(1,5)]+['Preserve'])

    def test_second_update_failure_rolls_back_first(self):
        with self.conn.cursor() as c:
            c.execute("ALTER TABLE prj.projects ADD CONSTRAINT test_failure CHECK (name != 'Correct 2')")
        self.conn.commit()
        with self.assertRaises(Exception): repair.repair(self.conn,'tenant-a',self.manifest,lambda _:None)
        self.assertEqual(self.names(),[f'Old {i}' for i in range(1,5)]+['Preserve'])

    def test_added_project_blocks_all_writes(self):
        with self.conn.cursor() as c:
            c.execute("INSERT INTO prj.projects(id,contract_id,code,name) VALUES (%s,%s,'second','Independent')",
                      (str(UUID(int=100)),self.rows[0]['contract_id']))
        self.conn.commit()
        with self.assertRaisesRegex(RuntimeError,'relationship'):
            repair.repair(self.conn,'tenant-a',self.manifest,lambda _:None)
        self.assertTrue(all(f'Old {i}' in self.names() for i in range(1,5)))

    def test_stale_snapshot_blocks_all_writes(self):
        with self.conn.cursor() as c:
            c.execute("UPDATE ctr.contracts SET name='Concurrent edit' WHERE id=%s",(self.rows[2]['contract_id'],))
        self.conn.commit()
        with self.assertRaisesRegex(RuntimeError,'snapshot'):
            repair.repair(self.conn,'tenant-a',self.manifest,lambda _:None)
        self.assertEqual(self.names(),[f'Old {i}' for i in range(1,5)]+['Preserve'])


if __name__=='__main__': unittest.main()
