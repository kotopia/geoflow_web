from django.contrib.auth import logout
from django.shortcuts import redirect
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.http import require_POST


@require_POST
@csrf_protect
def logout_view(request):
    """Terminate the authenticated session only through a CSRF-protected POST."""

    logout(request)
    request.session.flush()
    return redirect("login")
