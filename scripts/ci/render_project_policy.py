"""Render actual project templates with synthetic data; no DB or real users."""
from pathlib import Path
from types import SimpleNamespace as Row
import sys,types
from datetime import date,datetime
from unittest.mock import patch
from django.conf import settings
settings.configure(STATIC_URL='/static/',USE_TZ=False,USE_I18N=False,INSTALLED_APPS=[],DATABASES={})
import django;django.setup()
from django import forms
from django.template import Engine,Context,Library
acl=types.ModuleType('project_ui_acl');acl.register=Library()
@acl.register.simple_tag(takes_context=True)
def has_perm(context,value):return True
sys.modules['project_ui_acl']=acl
root=Path.cwd()
e=Engine(dirs=[str(root/'geoflow_ops/templates'),str(root/'control/templates')],libraries={'static':'django.templatetags.static','humanize':'django.contrib.humanize.templatetags.humanize','acl_tags':'project_ui_acl','workflow_tags':'project_ui_acl'})
c=Row(pk='contract-a',code='A26',name='계약명 원본')
rows=[Row(pk=str(i),contract=c,code=f'A26-00{i}',name=f'독립 프로젝트 {i}',status=status,status_key=status,status_label=label,start_date=date(2026,11,1),end_date=date(2026,12,1),modified_order=datetime(2026,11,i,12),manager_names='검증 담당자') for i,status,label in [(1,'active','진행'),(2,'complete','완료'),(3,'pause','중지')]]
ctx={'projects':rows,'status_counts':{'total':3,'active':1,'complete':1,'pause':1},'contract_options':[c],'can_create_project':True,'current_year':2026,'request':{'session':{},'user':{'is_authenticated':False}}}
class CreationForm(forms.Form):
 contract=forms.ChoiceField(choices=[('','선택'),('single','단일 계약'),('multiple','복수 계약')],widget=forms.Select(attrs={'class':'form-select'}))
 name=forms.CharField(required=False,widget=forms.TextInput(attrs={'class':'form-control'}))
 status=forms.ChoiceField(choices=[('active','진행'),('complete','완료')])
 start_date=forms.DateField(required=False);end_date=forms.DateField(required=False)
 description=forms.CharField(required=False,widget=forms.Textarea)
 confirm_duplicate=forms.BooleanField(required=False)
for field in CreationForm.base_fields.values():
 field.widget.attrs['class']='form-check-input' if isinstance(field.widget,forms.CheckboxInput) else ('form-select' if isinstance(field.widget,forms.Select) else 'form-control')
CreationForm.base_fields['contract'].label='연결 계약'
CreationForm.base_fields['name'].label='프로젝트명'
CreationForm.base_fields['status'].label='수행상태'
CreationForm.base_fields['start_date'].label='시작일'
CreationForm.base_fields['end_date'].label='종료일'
CreationForm.base_fields['description'].label='기타사항'
CreationForm.base_fields['description'].widget.attrs['rows']=3
CreationForm.base_fields['confirm_duplicate'].label='같은 계약의 중복 이름을 확인했습니다.'
out=Path('artifacts/project-policy');out.mkdir(parents=True,exist_ok=True)
with patch('django.urls.reverse',side_effect=lambda name,args=None,kwargs=None,**kw:'/'+str(name).replace(':','/')+'/'):
 (out/'list.html').write_text(e.get_template('geoflow_ops/projects/project_list.html').render(Context(ctx)))
 (out/'detail.html').write_text(e.get_template('geoflow_ops/projects/project_detail.html').render(Context({**ctx,'obj':Row(id='p1',pk='p1',name='독립 수행단위',code='A26-001',status_label='중지',start_date=date(2026,11,2),end_date=date(2026,11,20),updated_at=datetime(2026,11,3,12),description='프로젝트 비고',contract=Row(code='A26',name='계약명 원본',kind='용역',start_date=date(2026,1,1),end_date=date(2026,12,31))), 'can_edit_project':True,'contract_workflow':{'major_code':'execution','major_label':'수행','phase_class':'bg-success'}})))
 (out/'create.html').write_text(e.get_template('geoflow_ops/projects/project_form.html').render(Context({**ctx,'form':CreationForm(),'contract_names':{'single':{'name':'단일 계약 원본','single':True},'multiple':{'name':'복수 계약 원본','single':False}}})))
print('Rendered project list and creation fixtures')
