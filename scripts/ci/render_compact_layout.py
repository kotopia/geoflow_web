"""Render actual templates without application startup, DBs or credentials.

The ACL tag is a fixture stub; this checks presentation, not server authorization.
"""
from pathlib import Path
import sys,types
from django.conf import settings
settings.configure(STATIC_URL='/static/',USE_TZ=False,USE_I18N=False,INSTALLED_APPS=[],DATABASES={})
import django;django.setup()
from django.template import Engine,Context,Library
from unittest.mock import patch
from datetime import date,timedelta
acl=types.ModuleType('ui_acl');acl.register=Library()
@acl.register.simple_tag(takes_context=True)
def has_perm(context, value): return context.get("fixture_finance_permission", True)
sys.modules['ui_acl']=acl
root=Path.cwd()
e=Engine(dirs=[str(root/'geoflow_ops/templates'),str(root/'control/templates')],libraries={'static':'django.templatetags.static','humanize':'django.contrib.humanize.templatetags.humanize','acl_tags':'ui_acl'})
ctx=dict(today=date(2026,10,23),days=30,can_view_projects=True,can_view_directory=True,ending_count=7,bid_can_view=True,bid_can_manage=True,employee_can_list=True,employee_can_create=True,employee_can_manage_settings=True,central_is_staff=True,service_menus=dict(bids=True,gis=True,finance=True),request={'session':{},'user':{'is_authenticated':False}},cards=[dict(label=label,other=2,metrics=[dict(label=l,value=v,url='#') for l,v in [('전체',125),('진행',83),('완료',40)]]) for label in ['계약','프로젝트']],ending_rows=[dict(id=i,name='검증용 상수도 지하시설물 조사 프로젝트 '+str(i+1),manager='검증 담당자',end_date=date(2026,10,23)+timedelta(days=i*5),days_left=i*5,workflow=dict(phase_class='bg-success',major_label='수행')) for i in range(5)])
out=Path('artifacts/compact-layout');out.mkdir(parents=True,exist_ok=True)
with patch('django.urls.reverse',side_effect=lambda name,args=None,kwargs=None,**kw:'/'+str(name).replace(':','/')+'/'):
 for name,template in [('tenant','geoflow_ops/home.html'),('central','control/base_central.html'),('popup','geoflow_ops/finance/finance_import_popup_v2.html')]:
  (out/(name+'.html')).write_text(e.get_template(template).render(Context(ctx)))
 limited=dict(ctx, bid_can_view=False, bid_can_manage=False, employee_can_list=False, employee_can_create=False, employee_can_manage_settings=False, fixture_finance_permission=False, service_menus=dict(bids=False,gis=False,finance=False))
 (out/'limited.html').write_text(e.get_template('geoflow_ops/home.html').render(Context(limited)))
 # Component fixture uses the real base template, not a separate design.
 fixture='''{% extends "geoflow_ops/base_tenant.html" %}{% block content %}<h1 class="h3">계약정보 · 컴포넌트 검증</h1><div class="card"><div class="card-header"><h2 class="card-title">계약 기본정보</h2></div><div class="card-body"><label class="form-label">계약명</label><input class="form-control" value="검증용 상수도 지하시설물 조사 프로젝트"><div class="small">보조 설명 <small>중첩 설명</small></div><button class="btn btn-primary">저장</button><button class="btn btn-sm btn-secondary">열기</button><span class="badge bg-success">수행</span><span class="badge-xs">완료</span><table class="table"><thead><tr><th>계약명</th><th>금액</th></tr></thead><tbody><tr><td>검증 계약</td><td>1,250,000,000</td></tr></tbody></table><table class="table table-sm"><tbody><tr><td>촘촘한 표</td></tr></tbody></table></div></div>{% endblock %}'''
 (out/'components.html').write_text(e.from_string(fixture).render(Context(ctx)))
print('Rendered five actual-template fixtures; no DB configured')
