import logging

from django.contrib.auth import get_user_model, logout
from django.shortcuts import redirect
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters

from .services_identity import lookup_user_id_from_request
from .views_auth import login_view as central_login_view


logger = logging.getLogger(__name__)


@sensitive_post_parameters("email", "username", "password")
@never_cache
def login_view(request):
    """Keep auth_user as a non-privileged bridge only for central GeoFlow identities."""

    response = central_login_view(request)
    user = getattr(request, "user", None)
    if not getattr(user, "is_authenticated", False):
        return response

    try:
        central_user_id = lookup_user_id_from_request(request)
    except Exception:
        logger.error("AUTH: central identity confirmation failed")
        logout(request)
        request.session.flush()
        return redirect("login")

    # A standalone Django admin/dev account is not a GeoFlow session bridge.
    if not central_user_id:
        return response

    User = get_user_model()
    try:
        updated = User.objects.filter(pk=user.pk).update(
            is_active=True,
            is_staff=False,
            is_superuser=False,
        )
    except Exception:
        logger.error("AUTH: session bridge normalization failed")
        logout(request)
        request.session.flush()
        return redirect("login")

    if updated != 1:
        logger.error("AUTH: session bridge normalization unavailable")
        logout(request)
        request.session.flush()
        return redirect("login")

    user.is_active = True
    user.is_staff = False
    user.is_superuser = False
    return response
