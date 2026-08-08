from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from . import views_events
from .services.entity_access import require_tenant_context


@never_cache
@login_required
@require_GET
def event_list(request):
    """Return tenant event data without allowing browser/intermediary caching."""

    require_tenant_context(request)
    return views_events.list_events(request)
