"""Focused rehearsal only. Fixed disposable localhost DB; no runtime credentials.
Synthetic IDs/removed-field names are NOT production metadata identifiers.
"""
from pathlib import Path
from uuid import uuid5, NAMESPACE_URL
from collections import Counter
import hashlib
import json
import runpy
import subprocess
import psycopg2

import os
if os.environ.get('GEOFLOW_RUN_ISOLATED_POSTGIS') != '1':
    raise RuntimeError('Explicit isolated database opt-in required')
REPO = Path(__file__).resolve().parents[2]
BF_PATH = 'geoflow_ops/gis/business_fields.py'
bf = runpy.run_path(str(REPO/BF_PATH))
TABLES, REFS = bf['TABLES'], bf['REFERENCES']
uid = lambda name: str(uuid5(NAMESPACE_URL, 'geoflow-observed-fixture-only/'+name))
project = '86f52715-3cca-4124-9cc6-cb7c6a7e9c4e'
selected, other = uid('profile-base'), uid('profile-other')
DB = 'geoflow_observed_metadata_test'
opts = dict(host='127.0.0.1', port=55439, user='geoflow_test')
admin = psycopg2.connect(dbname='postgres', **opts)
admin.autocommit = True
with admin.cursor() as cur:
    cur.execute('SELECT 1 FROM pg_database WHERE datname=%s', [DB])
    if not cur.fetchone(): cur.execute('CREATE DATABASE '+DB)
admin.close()
conn = psycopg2.connect(dbname=DB, **opts)
cur = conn.cursor()
# Rebuild only a named disposable DB. No operational settings/locators imported.
cur.execute('DROP SCHEMA IF EXISTS gis CASCADE; DROP SCHEMA IF EXISTS prj CASCADE; DROP SCHEMA IF EXISTS hr CASCADE')
cur.execute('CREATE SCHEMA gis; CREATE SCHEMA prj; CREATE SCHEMA hr')
cur.execute('CREATE TABLE prj.projects(id uuid PRIMARY KEY,code text); CREATE TABLE hr.employee_profile(id uuid PRIMARY KEY,is_deleted boolean NOT NULL DEFAULT false)')
cur.execute('CREATE TABLE gis.profile(id uuid PRIMARY KEY,code text UNIQUE,active boolean NOT NULL)')
cur.execute('CREATE TABLE gis.project_profile(project_id uuid,profile_id uuid,status text)')
cur.execute('CREATE TABLE gis.meta_feature_type(id uuid PRIMARY KEY,physical_name text UNIQUE,active boolean NOT NULL)')
cur.execute('''CREATE TABLE gis.meta_field_def(id uuid PRIMARY KEY,feature_type_id uuid REFERENCES gis.meta_feature_type,
 physical_name text,standard_name text,label text,data_type text,code_group_key text,widget_type text,
 UNIQUE(feature_type_id,physical_name))''')
cur.execute('''CREATE TABLE gis.profile_field(id uuid PRIMARY KEY,profile_id uuid REFERENCES gis.profile,
 field_def_id uuid REFERENCES gis.meta_field_def,enabled boolean,required boolean,editable boolean,visible boolean,sort_order integer,
 UNIQUE(profile_id,field_def_id))''')
cur.execute('CREATE TABLE gis.ref_code_group(id uuid PRIMARY KEY,group_key text UNIQUE,active boolean)')
cur.execute('''CREATE TABLE gis.ref_code_value(id uuid PRIMARY KEY,group_id uuid REFERENCES gis.ref_code_group,
 code text,label text,active boolean,valid_from date,valid_to date,UNIQUE(group_id,code))''')
cur.execute("INSERT INTO gis.profile VALUES(%s,'GEOFLOW_BASE_V1',true),(%s,'FIXTURE_OTHER_PROFILE',true)",[selected,other])
cur.execute('INSERT INTO prj.projects VALUES(%s,%s)',[project,'26003'])
cur.executemany('INSERT INTO prj.projects VALUES(%s,%s)',[(uid('project'+str(i)),'fixture-'+str(i)) for i in range(762)])

def field(table, name, dtype='text'):
    fid = uid(table+'/'+name)
    cur.execute('INSERT INTO gis.meta_field_def VALUES(%s,%s,%s,%s,%s,%s,NULL,%s)',
                [fid,uid(table),name,name.upper(),'fixture-label',dtype,'text'])
    for profile in (selected, other):
        # Explicit restrictions must survive renames and metadata updates.
        cur.execute('INSERT INTO gis.profile_field VALUES(%s,%s,%s,true,true,false,false,17)',
                    [uid(profile+'/'+table+'/'+name),profile,fid])

for i, table in enumerate(TABLES):
    cur.execute('INSERT INTO gis.meta_feature_type VALUES(%s,%s,true)',[uid(table),table])
    refcols = ','.join('"'+name+'" text' for name in REFS[table])
    cur.execute(f'''CREATE TABLE gis.{table}(id uuid PRIMARY KEY,project_id uuid REFERENCES prj.projects,
      date date NULL,status text NOT NULL DEFAULT '미완료' CHECK(status IN ('미완료','완료','보완필요')),
      worker_id uuid NULL,{refcols})''')
    field(table,'ist_ymd','date')
    # Only aggregate count (2) was supplied; placement is explicitly synthetic.
    if table in ('wtl_pipe_lm','wtl_valv_ps'): field(table,'sys_chk')
    for name in REFS[table]: field(table,name)
    for n in range(7 if i==0 else 6): field(table,'fixture_removed_'+str(n))

for i,key in enumerate(sorted({key for mapping in REFS.values() for key in mapping.values()})):
    gid=uid(key);cur.execute('INSERT INTO gis.ref_code_group VALUES(%s,%s,true)',[gid,key])
    for n in range(9 if i==0 else 7):
        cur.execute('INSERT INTO gis.ref_code_value VALUES(%s,%s,%s,%s,true,NULL,NULL)',[uid(key+str(n)),gid,'fixture-'+str(n),'Fixture value'])
gid=uid('GEOFLOW.WORK_STATUS');cur.execute('INSERT INTO gis.ref_code_group VALUES(%s,%s,true)',[gid,'GEOFLOW.WORK_STATUS'])
for label in ('미완료','완료','보완필요'):
    cur.execute('INSERT INTO gis.ref_code_value VALUES(%s,%s,%s,%s,true,NULL,NULL)',[uid(label),gid,label,label])
cur.execute("INSERT INTO gis.wtl_pipe_lm(id,project_id,date) VALUES(%s,%s,'2001-02-03'),(%s,%s,NULL)",[uid('object1'),project,uid('object2'),project])
conn.commit()

def rows(table):
    cur.execute('SELECT to_jsonb(t) FROM '+table+' t ORDER BY id')
    return [row[0] for row in cur.fetchall()]

def digest(value):return hashlib.sha256(json.dumps(value,sort_keys=True,ensure_ascii=False).encode()).hexdigest()
