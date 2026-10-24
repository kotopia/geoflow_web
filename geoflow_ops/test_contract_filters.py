import json
from types import SimpleNamespace
from unittest.mock import patch, MagicMock
from django.test import SimpleTestCase, RequestFactory
from django.core.exceptions import PermissionDenied
from geoflow_ops.services.contract_filter_definition import validate_definition
from geoflow_ops.views_saved_filters import contract_saved_filters, preference_scope


class DefinitionTests(SimpleTestCase):
    def test_roundtrip_nested_numeric_date_and_string(self):
        tree={'logic':'AND','criteria':[
            {'origData':'amount','condition':'>=','value':['10000000']},
            {'logic':'OR','criteria':[{'origData':'client','condition':'contains','value':['충남']},{'origData':'client','condition':'contains','value':['대전']}]},
            {'origData':'start','condition':'between','value':['2023-01-01','2026-12-31']}]}
        result=validate_definition({'version':1,'conditions':tree,'order':[[7,'desc']]})
        self.assertEqual(result['conditions']['criteria'][0]['data'],'계약금액')
        self.assertEqual(validate_definition(result),result)

    def test_reject_injected_fields_operators_sizes_and_sort(self):
        for item in [
            {'origData':'amount); DROP TABLE ctr.contracts;--','condition':'=','value':['1']},
            {'origData':'amount','condition':'rawSQL','value':['1']},
            {'origData':'client','condition':'=','value':['x'*201]},
            {'origData':'amount','condition':'between','value':['1']},
        ]:
            with self.assertRaises(ValueError):validate_definition({'version':1,'conditions':{'criteria':[item]}})
        with self.assertRaises(ValueError):validate_definition({'version':1,'order':[[0,'desc']]})
        with self.assertRaises(ValueError):validate_definition({'version':1,'order':[[1,'DROP']]})

    def test_limits_and_canonical_alias(self):
        item={'origData':'name','data':'<script>','condition':'contains','value':['<script>']}
        result=validate_definition({'version':1,'conditions':{'criteria':[item]}})
        self.assertEqual(result['conditions']['criteria'][0]['data'],'계약명')
        with self.assertRaises(ValueError):validate_definition({'version':1,'conditions':{'criteria':[item]*31}})
        group={}
        for i in range(6):group={'criteria':[group]}
        with self.assertRaises(ValueError):validate_definition({'version':1,'conditions':group})


class SavedFilterBoundaryTests(SimpleTestCase):
    def request(self, method='get', body=None):
        factory=RequestFactory()
        req=factory.post('/contracts/saved-filters/',data=json.dumps(body or {}),content_type='application/json') if method=='post' else factory.get('/contracts/saved-filters/')
        req.user=SimpleNamespace(is_authenticated=True,email='member@example.invalid')
        req.session={'group_id':'00000000-0000-0000-0000-000000000001','tenant_db_alias':'tenant_a','gf_perms':['contracts.view']}
        return req

    @patch('geoflow_ops.views_saved_filters.connections')
    @patch('geoflow_ops.views_saved_filters.require_tenant_context',return_value='tenant_a')
    def test_identity_membership_and_tenant_mapping_verified(self, context, connections):
        cur=connections.__getitem__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value=['user-a']
        alias,user,group=preference_scope(self.request())
        self.assertEqual(user,'user-a')
        sql,params=cur.execute.call_args.args
        self.assertIn('m.status',sql);self.assertIn('c.db_alias=%s',sql)
        self.assertEqual(params,['member@example.invalid','00000000-0000-0000-0000-000000000001','tenant_a'])
        cur.fetchone.return_value=None
        with self.assertRaises(PermissionDenied):preference_scope(self.request())

    @patch('geoflow_ops.views_saved_filters.connections')
    @patch('geoflow_ops.views_saved_filters.require_tenant_context',return_value='tenant_a')
    def test_no_permission_or_missing_group_cannot_touch_storage(self, context, connections):
        req=self.request();req.session['gf_perms']=[]
        with self.assertRaises(PermissionDenied):contract_saved_filters(req)
        connections.__getitem__.assert_not_called()
        req=self.request();req.session.pop('group_id')
        with self.assertRaises(PermissionDenied):contract_saved_filters(req)
        connections.__getitem__.assert_not_called()

    @patch('geoflow_ops.views_saved_filters.connections')
    @patch('geoflow_ops.views_saved_filters.preference_scope',return_value=('default','user-a','group-a'))
    def test_reads_always_bind_user_group_module(self, scope, connections):
        cur=connections.__getitem__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value=['saved_filters'];cur.fetchall.return_value=[]
        response=contract_saved_filters(self.request())
        self.assertEqual(response.status_code,200)
        self.assertEqual(cur.execute.call_args.args[1],['user-a','group-a','contracts'])
        scope.return_value=('default','user-b','group-b')
        contract_saved_filters(self.request())
        self.assertEqual(cur.execute.call_args.args[1],['user-b','group-b','contracts'])

    @patch('geoflow_ops.views_saved_filters.transaction.atomic')
    @patch('geoflow_ops.views_saved_filters.connections')
    @patch('geoflow_ops.views_saved_filters.preference_scope',return_value=('default','user-a','group-a'))
    def test_save_ignores_client_scope_and_uses_parameters(self, scope, connections, atomic):
        cur=connections.__getitem__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.side_effect=[['saved_filters'],[0],['filter-id']]
        req=self.request('post',{'user_id':'other','group_id':'other','name':"x'); DROP TABLE users;--",'definition':{'version':1}})
        response=contract_saved_filters(req)
        self.assertEqual(response.status_code,200)
        sql,params=cur.execute.call_args.args
        self.assertNotIn('DROP',sql);self.assertEqual(params[1:4],['user-a','group-a','contracts'])

    @patch('geoflow_ops.views_saved_filters.connections')
    @patch('geoflow_ops.views_saved_filters.preference_scope',return_value=('default','user-a','group-a'))
    def test_missing_schema_and_invalid_payload_are_explicit(self, scope, connections):
        cur=connections.__getitem__.return_value.cursor.return_value.__enter__.return_value
        cur.fetchone.return_value=[None]
        self.assertEqual(contract_saved_filters(self.request()).status_code,503)
        cur.fetchone.return_value=['saved_filters']
        self.assertEqual(contract_saved_filters(self.request('post',{'name':'x','definition':{'version':999}})).status_code,400)
