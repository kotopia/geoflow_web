from __future__ import annotations

import os

from django.conf import settings


DEFAULT_TERMS_VERSION = "2026-08-08-v1"
DEFAULT_PRIVACY_VERSION = "2026-08-08-v1"
LEGAL_ESTABLISHED_DATE = "2026-08-08"
LEGAL_EFFECTIVE_DATE_LABEL = "GeoFlow 공개 회원가입 개시일"

REQUIRED_LEGAL_FIELDS = (
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

_DEFAULT_LEGAL_TEXT = {
    "GEOFLOW_LEGAL_OPERATOR_NAME": "geoflow-manager/GeoFlow",
    "GEOFLOW_LEGAL_ADDRESS": "대전광역시",
    "GEOFLOW_LEGAL_CONTACT_EMAIL": "kotopia79@naver.com",
    "GEOFLOW_PRIVACY_OFFICER_NAME": "peako",
    "GEOFLOW_PRIVACY_CONTACT_EMAIL": "kotopia79@naver.com",
    "GEOFLOW_PRIVACY_CONTACT_PHONE": "042-822-8636",
    "GEOFLOW_SIGNUP_RETENTION_POLICY": (
        "승인된 회원의 계정 개인정보는 회원 탈퇴 또는 계정 종료 시까지 보유하고, "
        "거절 또는 만료된 회원가입 신청정보는 거절·만료일로부터 1년간 보관한 후 "
        "파기합니다. 다만 관계 법령에 따라 별도 보존 의무가 있는 정보는 해당 "
        "법령에서 정한 기간 동안 분리 보관합니다."
    ),
    "GEOFLOW_DESTRUCTION_POLICY": (
        "보유기간이 경과하거나 처리 목적이 달성되어 개인정보가 불필요하게 된 "
        "경우 지체 없이 파기합니다. 전자적 파일은 복구 또는 재생이 어렵도록 "
        "안전한 방법으로 삭제하고, 관계 법령에 따라 보존해야 하는 정보는 별도로 "
        "분리 보관한 후 보존기간 종료 시 파기합니다."
    ),
    "GEOFLOW_THIRD_PARTY_DISCLOSURE": (
        "현재 회원가입 및 계정 운영을 위한 개인정보의 별도 제3자 제공은 없습니다. "
        "다만 정보주체가 사전에 동의하거나 법률에 특별한 규정이 있는 등 관계 "
        "법령에서 허용하는 경우는 예외로 합니다."
    ),
    "GEOFLOW_PROCESSING_OUTSOURCING_DISCLOSURE": (
        "Amazon Web Services(AWS)에 서버·데이터베이스·스토리지 인프라 운영을 "
        "위탁하며, 회원가입·계정 관련 데이터의 주 저장 위치는 서울 리전"
        "(ap-northeast-2)입니다."
    ),
    "GEOFLOW_EMAIL_PROCESSOR_DISCLOSURE": (
        "NAVER 메일 서비스를 회원가입 인증메일 발송에 사용하며, 인증메일 발송에 "
        "필요한 수신 이메일 주소와 메일 전송 관련 정보가 처리될 수 있습니다."
    ),
    "GEOFLOW_CROSS_BORDER_DISCLOSURE": (
        "GeoFlow는 회원가입·계정 관련 고객 콘텐츠를 AWS 서울 리전"
        "(ap-northeast-2)에 저장하도록 구성하며, 이를 별도 국외 리전으로 복제하도록 "
        "구성하지 않습니다. 이용 중인 외부 서비스의 처리구조 또는 법적 요구 등으로 "
        "개인정보의 국외 이전에 해당하는 처리가 발생하는 경우 관계 법령에 따라 "
        "필요한 사항을 고지하고 적법한 절차를 이행합니다."
    ),
    "GEOFLOW_COOKIE_DISCLOSURE": (
        "로그인 상태 유지와 CSRF 보호 등 서비스 제공 및 보안에 필요한 세션·보안 "
        "쿠키를 사용할 수 있습니다. 브라우저에서 쿠키 저장을 거부할 수 있으나 "
        "필수 쿠키를 차단하면 로그인 등 일부 기능이 제한될 수 있습니다. 현재 "
        "회원가입 과정에서 맞춤형 광고 추적을 목적으로 쿠키를 사용하지 않습니다."
    ),
}


def setting_or_env_text(name: str, *, default: str | None = None) -> str:
    """Resolve public legal configuration without exposing secret settings."""

    configured = getattr(settings, name, None)
    if isinstance(configured, str) and configured.strip():
        return configured.strip()

    raw = os.environ.get(name)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()

    fallback = _DEFAULT_LEGAL_TEXT.get(name, "") if default is None else default
    return fallback.strip() if isinstance(fallback, str) else ""


def legal_document_version(setting_name: str, *, default: str) -> str:
    return setting_or_env_text(setting_name, default=default)
