# control/views_signup.py
from django.shortcuts import render, redirect
from django.views.decorators.csrf import csrf_protect
from django.db import connections
from django.contrib import messages
import bcrypt

@csrf_protect
def signup_view(request):
    if request.method == "POST":
        email = (request.POST.get("email") or "").strip()
        password = request.POST.get("password") or ""
        name = (request.POST.get("name") or "").strip()

        if not email or not password:
            messages.error(request, "이메일/비밀번호를 입력하세요.")
            return render(request, "control/signup.html")

        pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()

        with connections["default"].cursor() as cur:
            # 이미 존재하면 에러
            cur.execute("SELECT 1 FROM users WHERE email=%s", [email])
            if cur.fetchone():
                messages.error(request, "이미 가입된 이메일입니다. 로그인 해주세요.")
                return render(request, "control/signup.html")

            cur.execute("""
                INSERT INTO users(id, email, password_hash, name_display, is_active, created_at, updated_at)
                VALUES (gen_random_uuid(), %s, %s, %s, TRUE, now(), now())
            """, [email, pw_hash, name or None])

        # 가입 완료 → 로그인 페이지로 안내
        messages.success(request, "가입이 완료되었습니다. 로그인 해주세요.")
        return redirect("/login/")

    return render(request, "control/signup.html")
