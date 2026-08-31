from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import JsonResponse
from django.shortcuts import render
from django.urls import reverse
from django.views.decorators.http import require_GET

from .models import ProcessEvent
from .services.entity_access import authorize_scope_read, require_tenant_context
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
    rows = (
        ProcessEvent.objects.using(alias)
        .exclude(status="void")
        .order_by("occurred_at", "created_at")[:2000]
    )
    result = []
    for event in rows:
        display = _display_policy_from_payload(event.payload)
        if not display["calendar_enabled"]:
            continue
        if not authorize_scope_read(request, alias, event.scope_type, event.scope_id):
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
                "stage": event.stage,
            },
        })
    return JsonResponse(result, safe=False)
