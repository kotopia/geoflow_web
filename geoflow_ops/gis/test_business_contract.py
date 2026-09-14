"""Pure planner and fail-closed catalog regressions, no live persistence."""
import copy
import unittest
from unittest.mock import patch
from .business_fields import TABLES, REFERENCES, COMMON, plan_contract, ContractConflict
from .reference_catalog import project_reference_catalog


def state():
    result={'profile':'selected','tables':{},'groups':{},'status_values':[('todo','미완료'),('done','완료'),('fix','보완필요')]}
    for table in TABLES:
        fields={}
        for n,(_,dtype,label,widget) in COMMON.items():
            fields[n]=dict(id=table+n,name=n,type=dtype,group='GEOFLOW.WORK_STATUS' if n=='status' else None,label=label,standard=n.upper(),widget=widget)
        for n,key in REFERENCES[table].items():
            fields[n]=dict(id=table+n,name=n,type='text',group=key,label=n,standard=n.upper(),widget='select')
        result['tables'][table]=dict(columns={n:f['type'] for n,f in fields.items()},feature_id=table,fields=fields,counts={},links={f['id']:[('selected',False,True,False,False,17),('other',True,False,True,True,2)] for f in fields.values()})
        result['groups'].update({k:True for k in REFERENCES[table].values()})
    result['groups']['GEOFLOW.WORK_STATUS']=True
    return result


class BusinessPlannerTests(unittest.TestCase):
    def test_current_contract_noop_preserves_explicit_restrictions(self):
        before=state();snapshot=copy.deepcopy(before)
        self.assertEqual(plan_contract(before),[]);self.assertEqual(before,snapshot)

    def test_missing_profile_link_adds_only_selected_profile(self):
        before=state();row=before['tables']['wtl_pipe_lm'];row['links'][row['fields']['worker_id']['id']]=[('other',False,True,False,False,17)]
        operations=plan_contract(before)
        self.assertEqual(len(operations),1);self.assertEqual(operations[0][1][1],'selected')

    def test_code_conflict_is_not_overwritten(self):
        before=state();before['tables']['wtl_pipe_lm']['fields']['saa_cde']['group']='OTHER'
        with self.assertRaises(ContractConflict):plan_contract(before)

    def test_automatic_date_worker_defaults_require_review(self):
        for name in ('date','worker_id'):
            before=state();before['tables']['wtl_pipe_lm']['column_details']={name:{'default':'now()'}}
            with self.assertRaises(ContractConflict):plan_contract(before)

    def test_status_default_must_be_existing_incomplete_code(self):
        before=state();row=before['tables']['wtl_pipe_lm']
        row['column_details']={'status':{'default':"'todo'::character varying"}}
        self.assertEqual(plan_contract(before),[])
        for default in ("'done'::text",'some_function()',"'미완료'::text"):
            row['column_details']['status']['default']=default
            with self.assertRaises(ContractConflict):plan_contract(before)

    def test_empty_catalog_does_not_open_database(self):
        with patch('geoflow_ops.gis.reference_catalog.connections') as db:
            for names in ([],set(),[' ','']):
                result=project_reference_catalog(using='tenant',standard_names=names)
                self.assertEqual(result['groups'],[]);self.assertEqual(result['binding_count'],0)
            db.__getitem__.assert_not_called()
