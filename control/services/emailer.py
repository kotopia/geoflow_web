from django.conf import settings
from django.core.mail import send_mail

def send_set_password_email(to_email: str, link: str) -> None:
    subject = "[GeoFlow] 비밀번호 설정 안내"
    body = f"""안녕하세요.

GeoFlow에 접근하실 수 있도록 비밀번호 설정 링크를 보내드립니다.
아래 링크는 24시간 동안만 유효합니다.

{link}

본인이 요청하지 않은 경우 이 메일을 무시하셔도 됩니다.
"""
    send_mail(subject, body, getattr(settings, "DEFAULT_FROM_EMAIL", "no-reply@geoflow.local"), [to_email], fail_silently=False)
