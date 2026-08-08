from __future__ import annotations

import os

from django.conf import settings
from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET


_REQUIRED_LEGAL_FIELDS = (
    ("GEOFLOW_LEGAL_OPERATOR_NAME", "서비스 운영자 명칭"),
    ("GEOFLOW_LEGAL_ADDRESS", "운영자 주소"),
    ("GEOFLOW_LEGAL_CONTACT_EMAIL", "서비스 문의 이메일"),
    ("GEOFLOW_PRIVACY_OFFICER_NAME", "개인정보 보호책임자"),
    ("GEOFLOW_PRIVACY_CONTACT_EMAIL", "개인정보 문의 이메일"),
    ("GEOFLOW_PRIVACY_CONTACT_PHONE", "개인정보 문의 전화번호"),
    ("GEOFLOW_SIGNUP_RETENTION_POLICY", "가입정보 보유·파기 기준"),
    ("GEOFLOW_DESTRUCTION_POLICY", "개인정보 파기 절차·방법"),
    ("GEOFLOW_THIRD_PARTY_DISCLOSURE", "개인정보 제3자 제공 고지"),
    ("GEOFLOW_PROCESSING_OUTSOURCING_DISCLOSURE", "개인정보 처리위탁 고지"),
    ("GEOFLOW_EMAIL_PROCESSOR_DISCLOSURE", "이메일 발송 처리 고지"),
    ("GEOFLOW_CROSS_BORDER_DISCLOSURE", "개인정보 국외이전 여부·고지"),
    ("GEOFLOW_COOKIE_DISCLOSURE", "쿠키·자동수집 장치 고지"),
)


def _setting_or_env_text(name: str, *, default: str = "") -> str:
    configured = getattr(settings, name, None)
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    raw = os.environ.get(name)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return default


def legal_documents_ready() -> bool:
    return all(
        _setting_or_env_text(name)
        for name, _label in _REQUIRED_LEGAL_FIELDS
    )


def _legal_context() -> dict[str, object]:
    values = {
        name: _setting_or_env_text(name)
        for name, _label in _REQUIRED_LEGAL_FIELDS
    }
    missing = [
        label
        for name, label in _REQUIRED_LEGAL_FIELDS
        if not values[name]
    ]
    return {
        "is_draft": bool(missing),
        "missing_legal_fields": missing,
        "operator_name": values["GEOFLOW_LEGAL_OPERATOR_NAME"],
        "operator_address": values["GEOFLOW_LEGAL_ADDRESS"],
        "legal_contact_email": values["GEOFLOW_LEGAL_CONTACT_EMAIL"],
        "privacy_officer_name": values["GEOFLOW_PRIVACY_OFFICER_NAME"],
        "privacy_contact_email": values["GEOFLOW_PRIVACY_CONTACT_EMAIL"],
        "privacy_contact_phone": values["GEOFLOW_PRIVACY_CONTACT_PHONE"],
        "signup_retention_policy": values["GEOFLOW_SIGNUP_RETENTION_POLICY"],
        "destruction_policy": values["GEOFLOW_DESTRUCTION_POLICY"],
        "third_party_disclosure": values["GEOFLOW_THIRD_PARTY_DISCLOSURE"],
        "processing_outsourcing_disclosure": values[
            "GEOFLOW_PROCESSING_OUTSOURCING_DISCLOSURE"
        ],
        "email_processor_disclosure": values["GEOFLOW_EMAIL_PROCESSOR_DISCLOSURE"],
        "cross_border_disclosure": values["GEOFLOW_CROSS_BORDER_DISCLOSURE"],
        "cookie_disclosure": values["GEOFLOW_COOKIE_DISCLOSURE"],
        "terms_version": _setting_or_env_text(
            "SIGNUP_TERMS_VERSION",
            default="2026-08-draft1",
        ),
        "privacy_version": _setting_or_env_text(
            "SIGNUP_PRIVACY_VERSION",
            default="2026-08-draft1",
        ),
    }


@require_GET
@never_cache
def terms_view(request):
    return render(request, "control/terms.html", _legal_context())


@require_GET
@never_cache
def privacy_view(request):
    return render(request, "control/privacy.html", _legal_context())
