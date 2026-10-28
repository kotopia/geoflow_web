"""Render synthetic company fixtures using the real AdminKit assets."""
from pathlib import Path
ROOT = Path(__file__).resolve().parents[2]
p=ROOT/'scripts/ci/test_company_overview.py'
exec(compile(p.read_text().split('from geoflow_ops import test_company_overview')[0],str(p),'exec'),{'__file__':str(p)})
from django.template.loader import render_to_string
from geoflow_ops.models import MyOrgUnit,ProcessEvent
from geoflow_ops.company_models import CompanyProfile,CompanyRegistration,CompanyCredit,CompanyRevenue
from geoflow_ops.company_forms import RegistrationForm
from django.test import RequestFactory
req = RequestFactory().get('/')
# Deterministic test token; no session or production secrets.
req.META['CSRF_COOKIE'] = 'a' * 32
from datetime import date,datetime,timezone
from uuid import uuid4
from decimal import Decimal
out=Path('/tmp/company-preview');out.mkdir(exist_ok=True)
obj=MyOrgUnit(id=uuid4(),name='지오플로우 엔지니어링',rep_name='홍길동',biz_no='000-00-00000',address='충청남도 천안시 · 예시 주소',phone='000-0000-0000',email='demo@example.com')
profile=CompanyProfile(company=obj,industry='측량 · 공간정보 · 엔지니어링',business='공간정보 구축과 지하시설물 측량, 공공 인프라의 디지털 전환을 지원합니다.',founded_on=date(2005,3,15),legal_form='주식회사',enterprise_size='중소기업')
registration=CompanyRegistration(id=uuid4(),company=obj,kind='registration',name='공공측량업',number='예시-001',occurred_on=date(2025,4,3),expires_on=date(2028,4,2),status='active',issuer='등록기관 예시');registration.evidence=[]
credit=CompanyCredit(company=obj,agency='평가기관 예시',rating_type='기업신용평가',grade='BBB+',evaluated_on=date(2026,6,1),expires_on=date(2027,5,31),representative=True)
revenue=CompanyRevenue(company=obj,year=2025,amount=Decimal(3810000000),source='예시 재무제표')
series=[{'year':2021+i,'headcount':n,'revenue':{'amount':str(a),'confirmed':True}} for i,(n,a) in enumerate([(25,1820000000),(29,2150000000),(None,0),(35,3180000000),(42,3810000000)])];series[2]['revenue']=None
context={'obj':obj,'profile':profile,'companies':[obj,MyOrgUnit(id=uuid4(),name='자회사 예시')],'headcount':46,'revenue':revenue,'credit':credit,'series':series,'years':5,'registrations':[registration],'active_registrations':1,'can_edit':True,'finance':True,'finance_edit':True,'today':date(2026,10,28),'events':[ProcessEvent(id=uuid4(),title='기업신용평가 BBB+ 갱신',occurred_at=date(2026,6,1),payload={'company_source_kind':'credit','company_source_id':str(credit.pk)}),ProcessEvent(id=uuid4(),title='공공측량업 등록',occurred_at=date(2025,4,3),payload={})]}
(out/'index.html').write_text(render_to_string('geoflow_ops/myinfo/company_overview.html',context))
(out/'edit.html').write_text(render_to_string('geoflow_ops/myinfo/company_edit.html',{'obj':obj,'kind':'registration','form':RegistrationForm(),'finance':True,'finance_edit':True,'heading':'업등록·신고·인증','purpose':'business_registration','records':[registration]}, request=req))
static=out/'static';static.mkdir(exist_ok=True)
for app in ['control','geoflow_ops']:
    target=static/app
    if not target.exists(): target.symlink_to(ROOT/app/'static'/app)
print('Rendered synthetic overview and editor')
