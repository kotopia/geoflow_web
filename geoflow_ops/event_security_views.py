from django.contrib.auth.decorators import login_required
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from . import views_workboard
from .services.entity_access import require_tenant_context


@never_cache
@login_required
@require_GET
def event_list(request):
    """Return the cross-department tenant workboard timeline without caching."""

    require_tenant_context(request)
    return views_workboard.workboard_event_list(request)
