# control/services_mail.py (신규 파일)
from django.db import connections
from django.conf import settings
from django.core.mail import send_mail
from django.urls import reverse

def send_invite_email_with_set_password_link(user_id: str, email: str):
    # 1) 토큰 만들기 (48시간 유효)
    with connections["default"].cursor() as cur:
        cur.execute("""
          INSERT INTO password_reset_tokens (user_id, expires_at)
          VALUES (%s, now() + interval '48 hours')
          RETURNING token::text
        """, [user_id])
        token = cur.fetchone()[0]

    # 2) 링크 구성
    base = getattr(settings, "SITE_ORIGIN", "http://127.0.0.1:8000")
    link = f"{base}{reverse('set_password', args=[token])}"

    # 3) 메일 발송(개발용: 콘솔 출력)
    subject = "[GeoFlow] 계정 활성화 및 비밀번호 설정"
    body = (f"{email} 님,\n\n"
            "아래 링크에서 비밀번호를 설정하면 로그인이 가능합니다.\n"
            f"{link}\n\n"
            "본 링크는 48시간 동안만 유효합니다.\n")
    send_mail(subject, body, getattr(settings, "DEFAULT_FROM_EMAIL", "noreply@geoflow.local"), [email], fail_silently=True)
