from __future__ import annotations

from django.shortcuts import render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_GET

from .legal_policy import (
    DEFAULT_PRIVACY_VERSION,
    DEFAULT_TERMS_VERSION,
    LEGAL_EFFECTIVE_DATE_LABEL,
    LEGAL_ESTABLISHED_DATE,
    REQUIRED_LEGAL_FIELDS,
    legal_document_version,
    setting_or_env_text,
)


_REQUIRED_LEGAL_FIELDS = REQUIRED_LEGAL_FIELDS


def legal_documents_ready() -> bool:
    return all(
        setting_or_env_text(name)
        for name, _label in _REQUIRED_LEGAL_FIELDS
    )


def _legal_context() -> dict[str, object]:
    values = {
        name: setting_or_env_text(name)
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
        "terms_version": legal_document_version(
            "SIGNUP_TERMS_VERSION",
            default=DEFAULT_TERMS_VERSION,
        ),
        "privacy_version": legal_document_version(
            "SIGNUP_PRIVACY_VERSION",
            default=DEFAULT_PRIVACY_VERSION,
        ),
        "legal_established_date": LEGAL_ESTABLISHED_DATE,
        "legal_effective_date_label": LEGAL_EFFECTIVE_DATE_LABEL,
    }


@require_GET
@never_cache
def terms_view(request):
    return render(request, "control/terms.html", _legal_context())


@require_GET
@never_cache
def privacy_view(request):
    return render(request, "control/privacy.html", _legal_context())
