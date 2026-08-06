# control/views_signup.py
from django.contrib import messages
from django.shortcuts import redirect, render
from django.views.decorators.csrf import csrf_protect

from .forms_signup import SignupRequestForm
from .services.signup_service import (
    SignupRequestInput,
    SignupRequestRejected,
    create_signup_request,
)

@csrf_protect
def signup_view(request):
    if request.method == "POST":
        form = SignupRequestForm(request.POST)
        if form.is_valid():
            cleaned = form.cleaned_data
            try:
                create_signup_request(
                    SignupRequestInput(
                        email=cleaned["email"],
                        password=cleaned["password"],
                        name_display=cleaned["name_display"],
                        contact_phone=cleaned["contact_phone"],
                        organization_name=cleaned["organization_name"],
                        signup_purpose=cleaned["signup_purpose"],
                    )
                )
            except SignupRequestRejected as exc:
                form.add_error(None, str(exc))
            else:
                messages.success(request, "가입 요청이 접수되었습니다. 승인 전에는 로그인할 수 없습니다.")
                return redirect("/login/")
    else:
        form = SignupRequestForm()

    return render(request, "control/signup.html", {"form": form})
