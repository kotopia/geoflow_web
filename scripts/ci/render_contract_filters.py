"""Actual contract/base templates with synthetic records, no application/DB boot."""
from pathlib import Path
import sys, types
from datetime import date
from decimal import Decimal
from unittest.mock import patch
from django.conf import settings
settings.configure(STATIC_URL='/static/', USE_TZ=False, USE_I18N=False, INSTALLED_APPS=[], DATABASES={})
import django
django.setup()
from django.template import Engine, Context, Library
acl=types.ModuleType('filter_acl'); acl.register=Library()
acl.register.simple_tag(takes_context=True)(lambda context, value: True)
# Named tag required by shared sidebar.
@acl.register.simple_tag(takes_context=True)
def has_perm(context, value):
    return value != 'finance.view' or context.get('finance_allowed', True)
sys.modules['filter_acl']=acl
wf=types.ModuleType('filter_workflow'); wf.register=Library()
@wf.register.simple_tag
def contract_workflow(c):
    if 'workflow' in c: return c['workflow']
    complete=c['code']=='24001'
    return dict(filter_key='complete' if complete else 'active',is_complete=complete,major_code='settlement' if complete else 'execution',major_label='완료' if complete else '수행',phase_class='bg-secondary' if complete else 'bg-success',active_event_labels=['중지'] if c['code']=='26002' else [],active_event_count=3 if c['code']=='26002' else 0,has_active_suspension=c['code']=='26002')
@wf.register.simple_tag
def contract_document_access(contract_id):
    return dict(allowed=True, can_approve=False, pending=[])
sys.modules['filter_workflow']=wf
root=Path.cwd()
engine=Engine(dirs=[str(root/'geoflow_ops/templates'),str(root/'control/templates')],libraries={'static':'django.templatetags.static','l10n':'django.templatetags.l10n','humanize':'django.contrib.humanize.templatetags.humanize','acl_tags':'filter_acl','workflow_tags':'filter_workflow'})
rows=[dict(id=f'00000000-0000-0000-0000-{i:012d}',code='24001' if i==1 else str(26000+i), name='시험 계약 '+str(i),start_date=date(2023,1,1),end_date=date(2024 if i==1 else 2026,12,31),amount=Decimal(i*10000000) if i!=12 else None,kind='service' if i<=10 else 'other',client={'name':'대전 기관' if i%2 else '충남 기관'},sub_client=None,org_unit={'label':'본사'}) for i in range(1,13)]
ctx=dict(contracts=rows,current_year=2026,request={'session':{},'user':{'is_authenticated':False}},service_menus={'finance':True,'gis':True},gf_contract_kind_labels={'service':'용역','other':'기타'},csrf_token='fixture-csrf-token')
out=Path('artifacts/contract-filters');out.mkdir(parents=True,exist_ok=True)
with patch('django.urls.reverse',side_effect=lambda name,args=None,kwargs=None,**kw: '/contracts/saved-filters/' if name.endswith('contract_saved_filters') else '/fixture/'+name.replace(':','/')+'/'+('/'.join(str(a) for a in (args or [])))):
    (out/'contracts.html').write_text(engine.get_template('geoflow_ops/contracts/contract_list.html').render(Context(ctx)))
    for code,label in [('preparation','준비'),('contract','계약'),('kickoff','착수'),('execution','수행'),('closeout','준공'),('complete','완료')]:
        obj={**rows[1], 'workflow':dict(major_code=code,major_label=label,major_event_label='검증용 기준 이벤트'), 'description':'검증용 계약', 'org_unit':{'name':'본사'}}
        (out/('detail-'+code+'.html')).write_text(engine.get_template('geoflow_ops/contracts/contract_detail.html').render(Context({**ctx,'obj':obj,'edit_mode':False})))
    (out/'detail-denied.html').write_text(engine.get_template('geoflow_ops/contracts/contract_detail.html').render(Context({**ctx,'obj':obj,'edit_mode':False,'finance_allowed':False})))
print('Rendered actual contract list and all six detail workflow stages; synthetic data only')
