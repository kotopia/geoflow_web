"""Transactional migration/API rehearsal. Only a dedicated localhost CI DB is accepted."""
import os,sys,json,importlib
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from django.conf import settings
if os.environ.get('GEOFLOW_FILTER_TEST_DB') != 'ci_contract_filters':
    raise SystemExit('Dedicated disposable database opt-in required')
settings.configure(SECRET_KEY='isolated-filter-rehearsal',INSTALLED_APPS=['django.contrib.auth','django.contrib.contenttypes','control','control.catalog','geoflow_ops'],CENTRAL_DB_ALIAS='default',DATABASES={'default':{'ENGINE':'django.db.backends.postgresql','HOST':'127.0.0.1','PORT':os.environ.get('GEOFLOW_FILTER_TEST_PORT','5432'),'NAME':'ci_contract_filters','USER':'postgres','PASSWORD':os.environ['GEOFLOW_FILTER_TEST_PASSWORD']}})
import django
django.setup()
from django.db import connection,transaction
from django.test import RequestFactory
from django.core.exceptions import PermissionDenied
from geoflow_ops.views_saved_filters import contract_saved_filters
uid=lambda n:f'00000000-0000-0000-0000-{n:012d}'
with transaction.atomic():
    with connection.cursor() as cur:
        cur.execute('CREATE TABLE users(id uuid PRIMARY KEY,email text,is_active boolean)')
        cur.execute('CREATE TABLE groups(id uuid PRIMARY KEY,status text)')
        cur.execute('CREATE TABLE user_group_map(user_id uuid,group_id uuid,status text)')
        cur.execute('CREATE TABLE group_db_config(group_id uuid,db_alias text)')
        for n in (1,2):
            cur.execute('INSERT INTO users VALUES(%s,%s,true)',[uid(n),f'user{n}@example.invalid'])
            cur.execute("INSERT INTO groups VALUES(%s,'active')",[uid(n)])
            cur.execute('INSERT INTO group_db_config VALUES(%s,%s)',[uid(n),f'tenant_{n}'])
        for user,group in [(1,1),(2,1),(1,2)]:cur.execute("INSERT INTO user_group_map VALUES(%s,%s,'active')",[uid(user),uid(group)])
        migration=importlib.import_module('control.migrations.0008_saved_filters').Migration
        cur.execute(migration.operations[0].sql)
    factory=RequestFactory()
    def call(user,group,body=None,alias=None):
        req=factory.post('/contracts/saved-filters/',json.dumps(body),content_type='application/json') if body is not None else factory.get('/contracts/saved-filters/')
        req.user=SimpleNamespace(is_authenticated=True,email=f'user{user}@example.invalid')
        req.session={'group_id':uid(group),'tenant_db_alias':alias or f'tenant_{group}','gf_perms':['contracts.view']}
        with patch('geoflow_ops.services.entity_access.current_db_alias',return_value=req.session['tenant_db_alias']):return contract_saved_filters(req)
    body={'name':'개인 조건','definition':{'version':1,'conditions':{'logic':'AND','criteria':[{'origData':'amount','condition':'>=','value':['10000000']}]},'order':[[7,'desc']]}}
    a=json.loads(call(1,1,body).content);assert a['name']=='개인 조건'
    assert json.loads(call(2,1).content)['filters']==[]
    assert json.loads(call(1,2).content)['filters']==[]
    assert len(json.loads(call(1,1).content)['filters'])==1
    assert json.loads(call(1,1,body).content)['id']==a['id'] # upsert, not duplicate
    body['name']="x'); DROP TABLE users;--"
    assert call(1,1,body).status_code==200
    try:call(1,1,alias='tenant_2');raise AssertionError('mismatched alias accepted')
    except PermissionDenied:pass
    try:call(2,2);raise AssertionError('non-member accepted')
    except PermissionDenied:pass
    with connection.cursor() as cur:
        cur.execute('DELETE FROM users WHERE id=%s',[uid(1)])
        cur.execute('SELECT count(*) FROM saved_filters');assert cur.fetchone()[0]==0
    transaction.set_rollback(True)
print('PASS PostgreSQL DDL, API roundtrip/upsert, user+tenant isolation, mismatched mapping, nonmember denial, SQL-safe values, identity deletion cascade; rolled back fixture')
