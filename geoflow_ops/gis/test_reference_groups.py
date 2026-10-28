"""Applicability is scoped to a project's L2-to-layer context, never its name."""
import copy
import unittest
from unittest.mock import MagicMock, patch
from django.test import RequestFactory
from .central_definitions import resolve, reference_payload, validate_attributes
from .reference_groups import scope_layers
from .form_definitions import DefinitionError
from .qgis_manifest import build_qgis_manifest
from .server_snapshot_cache import snapshot_fingerprint


def fixture():
    layers = [{'id': key, 'standard_name': key.upper(), 'label': key, 'active': True} for key in ('water','electric')]
    fields = [dict(id=key, source_layer_id=key, physical_name='material', standard_name='MATERIAL',
                   label='관종', kind='text', widget_type='combo', sort_order=0, visible=True,
                   required=False, readonly=False) for key in ('water','electric')]
    codes = [dict(id=key+'-'+value, field_id=key, code=value, label=value, sort_order=i, enabled=True)
             for key in ('water','electric') for i,value in enumerate(('PE','K2','EP','AC'))]
    links = [dict(code_id=key+'-'+value, group_id=g) for key in ('water','electric')
             for value,groups in [('K2',['d']),('EP',['d','a']),('AC',['a'])] for g in groups]
    data = dict(layers=layers, fields=fields, codes=codes, groups=[dict(id='d',name='업무그룹1'),dict(id='a',name='업무그룹2')],
                group_fields=[], group_layers=[], rules=[], code_groups=links,
                layer_catalogs=[dict(layer_id='water',catalog_level=2,catalog_item_id='w'),
                                dict(layer_id='electric',catalog_level=3,catalog_item_id='e3')])
    config = dict(group_id=None, additions={}, private_items={}, overrides={}, reference_groups={'w':['a']},
                  reference_scope_layers=scope_layers(data,[{'2':'w'},{'2':'e','3':'e3'}]))
    return data, config


def values(definition, layer='water'):
    return [r['value'] for r in next(f for f in definition['fields'] if f['layer_id']==layer)['reference_codes']]


class ReferenceGroupTests(unittest.TestCase):
    def test_scope_specific_common_single_and_multi_group_codes(self):
        data, config = fixture()
        result=resolve(data,config,data['layers'])
        self.assertEqual(values(result), ['PE','EP','AC'])
        self.assertEqual(values(result,'electric'), ['PE'])
        config['reference_groups']['w']=['d']
        self.assertEqual(values(resolve(data,config,data['layers'])), ['PE','K2','EP'])
        config['reference_groups']['w']=['a','d']
        self.assertEqual(values(resolve(data,config,data['layers'])), ['PE','K2','EP','AC'])

    def test_no_group_preserves_common_and_form_group_does_not_grant_values(self):
        data, config=fixture(); config['reference_groups']={}; config['group_id']='d'
        self.assertEqual(values(resolve(data,config,data['layers'])), ['PE'])

    def test_legacy_codes_have_no_implicit_regional_assignment(self):
        data,config=fixture();data['code_groups']=[]
        self.assertEqual(values(resolve(data,config,data['layers'])), ['PE','K2','EP','AC'])

    def test_unrelated_or_stale_scope_assignments_do_not_leak(self):
        data, config=fixture();config['reference_groups']={'foreign':['d']}
        result=resolve(data,config,data['layers'])
        self.assertEqual(values(result),['PE']); self.assertEqual(values(result,'electric'),['PE'])

    def test_deleted_group_is_not_silently_treated_as_common(self):
        data,config=fixture();config['reference_groups']['w']=['deleted']
        with self.assertRaises(DefinitionError):resolve(data,config,data['layers'])

    def test_same_layer_multiple_linked_scopes_union_only_their_groups(self):
        data,config=fixture();config['reference_scope_layers']['e'].append('water')
        config['reference_groups']['e']=['d']
        self.assertEqual(values(resolve(data,config,data['layers'])),['PE','K2','EP','AC'])

    def test_reference_catalog_matches_final_form_for_each_layer(self):
        data,config=fixture();final=resolve(data,config,data['layers'])
        payload=reference_payload(data,['water','electric'],definition=final)
        for binding in payload['bindings']:
            group=next(g for g in payload['groups'] if g['code_group_key']==binding['code_group_key'])
            self.assertEqual([r['code'] for r in group['values']],values(final,binding['layer_id']))
        # A nonproject reader receives common values, never every restricted code.
        self.assertEqual([v['code'] for v in reference_payload(data,['water'])['groups'][0]['values']],['PE'])

    def test_direct_write_and_empty_allowed_domain_fail_closed(self):
        data,config=fixture();final=resolve(data,config,data['layers'])
        with self.assertRaises(DefinitionError):validate_attributes({'form_definition':final},'WATER',{'material':'K2'})
        validate_attributes({'form_definition':final},'WATER',{'material':'PE'})
        data['codes']=[r for r in data['codes'] if r['code']=='K2']
        final=resolve(data,config,data['layers'])
        self.assertEqual(values(final),[])
        with self.assertRaises(DefinitionError):validate_attributes({'form_definition':final},'WATER',{'material':'arbitrary'})
        validate_attributes({'form_definition':final},'WATER',{'material':None})

    def test_disabled_code_stays_invalid(self):
        data,config=fixture();data['codes'][0]['enabled']=False
        with self.assertRaises(DefinitionError):
            validate_attributes({'form_definition':resolve(data,config,data['layers'])},'WATER',{'material':'PE'})

    def test_group_and_relation_changes_change_final_catalog_manifest_revision(self):
        data,config=fixture();old=resolve(data,config,data['layers'])
        old_ref=reference_payload(data,['water'],definition=old)['revision']
        data['code_groups'].append(dict(code_id='water-K2',group_id='a'))
        new=resolve(data,config,data['layers'])
        self.assertNotEqual(old['revision'],new['revision'])
        self.assertNotEqual(old_ref,reference_payload(data,['water'],definition=new)['revision'])
        plans=[dict(layers=data['layers'],definition={'version':f['version'],'revision':f['revision']},form_definition=f) for f in (old,new)]
        manifests=[build_qgis_manifest(project={'id':'project'},plan=p,can_write=True,package_url='/package/',package_layers=[],realtime_supported=False) for p in plans]
        self.assertNotEqual(manifests[0]['transport']['form_definition_revision'],manifests[1]['transport']['form_definition_revision'])

    def test_snapshot_namespace_changes_with_filtered_definition(self):
        data,config=fixture();old=resolve(data,config,data['layers'])
        config['reference_groups']['w']=['d'];new=resolve(data,config,data['layers'])
        keys=[snapshot_fingerprint(alias='tenant',project_id='project',plan={'definition':f},layer_manifest=[]) for f in (old,new)]
        self.assertNotEqual(*keys)

    def test_project_settings_reject_viewer_before_persistence(self):
        from django.core.exceptions import PermissionDenied
        from types import SimpleNamespace
        from . import form_definition_views as views
        request=RequestFactory().post('/',{'action':'reference_groups'})
        request.user=SimpleNamespace(is_authenticated=True)
        with patch.object(views,'_require_gis_view',return_value='tenant'), \
             patch.object(views,'_require_project_gis_access',return_value=(SimpleNamespace(id='project'),{'layers':[]})), \
             patch.object(views,'project_access_policy',return_value=SimpleNamespace(can_edit_project=lambda value:False)), \
             patch.object(views.central,'central_snapshot') as snapshot:
            with self.assertRaises(PermissionDenied):views.project_configuration(request,'project')
            snapshot.assert_not_called()
