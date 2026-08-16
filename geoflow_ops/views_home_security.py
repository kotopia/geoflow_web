from django.conf import settings
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from geoflow_ops import views_dashboard
from geoflow_ops.services.entity_access import require_tenant_context


@login_required
def tenant_home(request):
    """Enter the tenant dashboard only from an authenticated, current tenant session."""

    central_alias = getattr(settings, "CENTRAL_DB_ALIAS", "default")
    if request.session.get("tenant_db_alias") == central_alias:
        return redirect("control:dashboard")
    if not request.session.get("group_id"):
        return redirect("control:dashboard")

    require_tenant_context(request)
    return views_dashboard.tenant_dashboard(request)
