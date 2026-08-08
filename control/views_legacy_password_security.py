from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_variables

from .views_users_admin import set_password_view as legacy_set_password_view


@sensitive_variables("token")
@never_cache
def legacy_password_setup_view(request, token):
    """Preserve the legacy password flow while suppressing token referrer leakage."""

    response = legacy_set_password_view(request, token)
    response["Referrer-Policy"] = "no-referrer"
    response["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
    response["Pragma"] = "no-cache"
    return response
