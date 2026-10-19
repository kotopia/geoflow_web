from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.db.models import Q
from django.utils.dateparse import parse_date
from control.gf_authz.permissions import gf_has_perm
from .models import Contract, Project
from .process_workflow import EVENT_TYPE_CHOICES
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from .models import ProcessEvent
from .services.entity_access import can_read_event, require_tenant_context
from .views_events import _display_policy_from_payload


@login_required
@require_GET
def calendar_page(request):
    require_tenant_context(request)
    return render(request, "geoflow_ops/calendar/calendar.html")


@login_required
@require_GET
def calendar_events(request):
    alias = require_tenant_context(request)
    overview = request.GET.get('overview') == '1'
    try:
        start = parse_date((request.GET.get('start') or '')[:10])
        end = parse_date((request.GET.get('end') or '')[:10])
    except ValueError:
        return JsonResponse({'error': 'Invalid calendar range'}, status=400)
    if overview and (not start or not end or not 0 < (end-start).days <= 62):
        return JsonResponse({'error': 'Invalid calendar range'}, status=400)
    query = Q()
    if start and end:
        query = (Q(due_at__gte=start, due_at__lt=end)
                 | Q(due_at__isnull=True, occurred_at__gte=start, occurred_at__lt=end)
                 | Q(due_at__isnull=True, payload__display__end_at__gte=start.isoformat(), payload__display__end_at__lt=end.isoformat()))
    if overview:
        query &= Q(payload__display__calendar_enabled=True, scope_type__in=['contract', 'project'])
    rows = (
        ProcessEvent.objects.using(alias)
        .filter(query)
        .exclude(status="void")
        .order_by("occurred_at", "created_at", "id")[:2001 if overview else 2000]
    )
    if overview:
        rows = list(rows)
        if len(rows) > 2000:
            return JsonResponse({'error': 'Calendar range exceeds 2000 events; use the calendar detail page.'}, status=422)
    result = []
    for event in rows:
        display = _display_policy_from_payload(event.payload)
        if not display["calendar_enabled"]:
            continue
        if not can_read_event(request, alias, event):
            continue
        date_value = event.due_at
        if not date_value and display["end_at"]:
            date_value = display["end_at"]
        if not date_value:
            date_value = event.occurred_at
        if not date_value:
            continue
        if hasattr(date_value, "isoformat"):
            date_value = date_value.isoformat()
        if start and end and not start.isoformat() <= str(date_value)[:10] < end.isoformat():
            continue
        target_url = None
        if event.scope_type == "contract":
            target_url = reverse("tenant:contract_detail", kwargs={"pk": event.scope_id})
        elif event.scope_type == "project":
            target_url = reverse("tenant:project_detail", kwargs={"pk": event.scope_id})
        result.append({
            "id": str(event.id),
            "title": event.title or event.event_type or "업무 이벤트",
            "start": str(date_value),
            "allDay": True,
            "url": target_url,
            "extendedProps": {
                "scope_type": event.scope_type,
                "event_type": event.event_type,
                **({"stage": event.stage,
                "scope_id": str(event.scope_id),
                "assignee_id": str(event.assignee_employee_id) if event.assignee_employee_id else None,
                "history": event.status == 'done',
                "kind": dict((c.code, c.label) for c in EVENT_TYPE_CHOICES).get(event.event_type, event.event_type),} if overview else {}),
            },
        })
    if overview:
        # Names are resolved only after the exact event authorization above.
        names = {}
        for scope, model in [('contract', Contract), ('project', Project)]:
            ids = [r['extendedProps']['scope_id'] for r in result if r['extendedProps']['scope_type'] == scope]
            names.update({(scope, str(pk)): name for pk, name in model.objects.using(alias).filter(pk__in=ids).values_list('id','name')})
        employees = {}
        if gf_has_perm(request, 'directory.view'):
            from django.db import connections
            ids = list({r['extendedProps']['assignee_id'] for r in result if r['extendedProps']['assignee_id']})
            if ids:
                with connections[alias].cursor() as cursor:
                    cursor.execute('SELECT id::text, name FROM hr.employee_profile WHERE id=ANY(%s::uuid[]) AND is_deleted=false', [ids])
                    employees = dict(cursor.fetchall())
        for item in result:
            props = item['extendedProps']
            props['scope_name'] = names.get((props['scope_type'], props['scope_id']), '업무 일정')
            assignee_id = props.pop('assignee_id', None)
            props['assignee'] = employees.get(assignee_id, '미지정') if gf_has_perm(request, 'directory.view') else '열람 제한'
        response = JsonResponse(result, safe=False)
        response['Cache-Control'] = 'private, no-store'
        response['X-Calendar-Limit'] = '2000'
        return response
    return JsonResponse(result, safe=False)
