from django.contrib import messages
from django.contrib.auth import logout
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_http_methods

from .services.central_password_change_service import (
    CentralPasswordChangeAuthenticationError,
    CentralPasswordChangeError,
    CentralPasswordChangeValidationError,
    change_authenticated_central_password,
)
from .services_identity import lookup_user_id_from_request


@sensitive_post_parameters("current_password", "new_password", "new_password2")
@sensitive_variables("current_password", "new_password", "new_password2")
@login_required
@never_cache
@csrf_protect
@require_http_methods(["GET", "POST"])
def account_password_change_view(request):
    if request.method == "GET":
        return render(request, "control/account_password_change.html")

    current_password = request.POST.get("current_password") or ""
    new_password = request.POST.get("new_password") or ""
    new_password2 = request.POST.get("new_password2") or ""

    if not current_password or not new_password or new_password != new_password2:
        messages.error(
            request,
            "현재 비밀번호와 새 비밀번호 확인 값을 다시 확인하세요.",
        )
        return render(request, "control/account_password_change.html")

    user_id = lookup_user_id_from_request(request)
    if not user_id:
        logout(request)
        messages.error(request, "계정 정보를 확인할 수 없어 다시 로그인해야 합니다.")
        return redirect("login")

    try:
        change_authenticated_central_password(
            user_id=user_id,
            current_password=current_password,
            new_password=new_password,
        )
    except CentralPasswordChangeAuthenticationError:
        messages.error(request, "현재 비밀번호를 확인할 수 없습니다.")
        return render(request, "control/account_password_change.html")
    except CentralPasswordChangeValidationError:
        messages.error(
            request,
            "새 비밀번호가 보안 조건에 맞지 않거나 기존 비밀번호와 같습니다.",
        )
        return render(request, "control/account_password_change.html")
    except CentralPasswordChangeError:
        messages.error(request, "비밀번호 변경을 완료할 수 없습니다.")
        return render(request, "control/account_password_change.html")

    # The service rotates the Django bridge auth hash. End this session explicitly
    # so the user must authenticate again with the new central password.
    logout(request)
    messages.success(request, "비밀번호가 변경되었습니다. 새 비밀번호로 다시 로그인하세요.")
    return redirect("login")
