"""Render production bid templates with synthetic data and no external/DB calls."""
import os
import re
import sys
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ['DJANGO_SETTINGS_MODULE'] = 'procurement.test_settings'
import django
django.setup()
from django.template import Context, Engine
from geoflow_ops.bids.detail import presentation
from geoflow_ops.bids.tenant_state import apply_progress

out = ROOT / 'artifacts/bid-detail'
out.mkdir(parents=True, exist_ok=True)
engine = Engine(libraries={'humanize':'django.contrib.humanize.templatetags.humanize'})
now = datetime(2026, 11, 23, 10, tzinfo=ZoneInfo('Asia/Seoul'))

def render(name, context):
    source = (ROOT / 'geoflow_ops/templates/geoflow_ops/bids' / (name + '.html')).read_text()
    source = re.sub(r'{% extends .*?%}', '', source)
    source = re.sub(r"{% url 'tenant:bid_notice_detail'.*?%}", '/detail/', source)
    source = re.sub(r"{% url 'tenant:bid_progress_save'.*?%}", '/bids/00000000-0000-0000-0000-000000000001/progress/', source)
    source = re.sub(r'{% url .*?%}', '/action/', source)
    return engine.from_string(source).render(Context(context))

for source in ('g2b','kepco','history'):
    n = presentation(dict(id='00000000-0000-0000-0000-000000000001', source=source,
        source_label='한국전력' if source == 'kepco' else '나라장터', bid_notice_no='EXAMPLE',
        title='예시 공고 · 지하시설물 측량 용역', notice_agency_name='예시 발주기관',
        posted_at=now-timedelta(days=1), bid_begin_at=now+timedelta(days=1),
        bid_close_at=now+timedelta(days=7), open_at=None if source == 'kepco' else now+timedelta(days=8),
        budget_amount='250000000', basic_amount='220000000', estimated_price='200000000', memo='기존 공유 기록',
        qualification_text='공공측량업 등 상세 자격은 공고문 참조',
        original_url='https://srm.kepco.net/' if source == 'kepco' else 'https://www.g2b.go.kr/',
        attachments=[dict(name='예시공고문.pdf', url='https://srm.kepco.net/example.pdf' if source == 'kepco' else 'https://www.g2b.go.kr/example.pdf')],
        collected_fields=[dict(label='공고 / 알 수 없는 필드',value='<script>원본은 텍스트로 표시</script>')]), {}, now=now)
    apply_progress(n, dict(registered_at=now, submitted_at=None, progress_badge='참가') if source != 'history' else {})
    n['saved'] = True
    context = dict(central_mode=True, page_links=[dict(label=1,active=True,query='page=1'),dict(label=2,active=False,query='page=2')], next_query='page=2', n=n,notices=[n],can_review=source!='history',read_only=source=='history',
        legacy_history=source=='history',return_to='/bids/?company=',personal_view='all',csrf_token='fixture-token')
    (out / (source+'-detail.html')).write_text(render('notice_detail', context))
    html = render('notice_list', context)
    (out / (source+'.html')).write_text('<!doctype html><html lang="ko"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><link rel="stylesheet" href="/static/control/css/light.css"></head><body><main class="p-3">'+html+'</main><script src="/static/control/js/app.js"></script></body></html>')
    if source == 'g2b':
        context['notices'] = [n,dict(n,id='00000000-0000-0000-0000-000000000002',saved=False,title='미등록 예시 공고',budget_amount=0)]
        bulk = render('notice_list',context)
        (out / 'g2b-bulk.html').write_text('<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/static/control/css/light.css"></head><body>'+bulk+'<script src="/static/control/js/app.js"></script></body></html>')
print('Rendered G2B, KEPCO, and read-only history with real AdminKit templates')

calendar_source = (ROOT / 'geoflow_ops/templates/geoflow_ops/calendar/calendar.html').read_text()
calendar_source = re.sub(r'{% extends .*?%}|{% load static %}', '', calendar_source)
calendar_source = re.sub(r'{% static .*?%}', '/static/control/js/fullcalendar.js', calendar_source)
calendar_source = re.sub(r'{% url .*?%}', '/events/', calendar_source)
calendar_source = calendar_source.replace('{{ block.super }}', '')
calendar_html = engine.from_string(calendar_source).render(Context({}))
(out / 'calendar.html').write_text('<!doctype html><html><head><meta charset="utf-8"><link rel="stylesheet" href="/static/control/css/light.css"></head><body>'+calendar_html+'</body></html>')
