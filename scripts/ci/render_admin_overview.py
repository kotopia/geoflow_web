import os, sys
sys.path.insert(0, os.getcwd())
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'geoflow_project.settings')
import django
django.setup()
from pathlib import Path
from datetime import date,timedelta
from django.template.loader import get_template
from unittest.mock import patch
from types import SimpleNamespace as Row
from geoflow_ops.services.dashboard import summary_card
sample=[Row(id=i) for i in range(8)]
states={str(i):{'filter_key':'active' if i<5 else 'complete'} for i in range(8)}
context={'today':date(2026,10,19),'days':30,'can_view_contracts':True,'can_view_projects':True,'can_view_directory':True,'cards':[summary_card(x,'/'+x,sample,states) for x in ['계약','프로젝트']], 'ending_count':7, 'ending_rows':[{'id':i,'name':'검증용 프로젝트 '+str(i+1),'manager':'검증 담당자','end_date':date(2026,10,19)+timedelta(days=i*5),'days_left':i*5,'workflow':{'phase_class':'bg-success','major_label':'수행'}} for i in range(5)],'request':Row(session={},user=Row(is_authenticated=False))}
with patch('django.urls.reverse',side_effect=lambda name,args=None,kwargs=None,**kw:'/'+str(name).replace(':','/')+'/'):
 html=get_template('geoflow_ops/home.html').render(context)
Path('artifacts/admin-overview').mkdir(parents=True, exist_ok=True)
Path('artifacts/admin-overview/index.html').write_text(html)
