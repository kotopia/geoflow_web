from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass
from urllib.parse import urlsplit

from django.conf import settings

from control.legal_policy import DEFAULT_PRIVACY_VERSION, DEFAULT_TERMS_VERSION
from control.services.signup_runtime_readiness import signup_public_runtime_ready


CANONICAL_PRODUCTION_ORIGIN = "https://geoflow.co.kr"
CANONICAL_PRODUCTION_HOST = "geoflow.co.kr"


@dataclass(frozen=True)
class ProductionRuntimeCheck:
    code: str
    status: str
    message: str


@dataclass(frozen=True)
class ProductionRuntimePreflight:
    checks: tuple[ProductionRuntimeCheck, ...]

    @property
    def ready(self) -> bool:
        return not any(check.status == "FAIL" for check in self.checks)


def _check(code: str, status: str, message: str) -> ProductionRuntimeCheck:
    return ProductionRuntimeCheck(code=code, status=status, message=message)


def _environment_or_setting_text(
    settings_obj,
    environ: Mapping[str, str],
    name: str,
) -> str:
    raw = environ.get(name)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    configured = getattr(settings_obj, name, None)
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return ""


def _setting_or_environment_text(
    settings_obj,
    environ: Mapping[str, str],
    name: str,
) -> str:
    configured = getattr(settings_obj, name, None)
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    raw = environ.get(name)
    if isinstance(raw, str) and raw.strip():
        return raw.strip()
    return ""


def _setting_or_environment_bool(
    settings_obj,
    environ: Mapping[str, str],
    name: str,
) -> bool:
    configured = getattr(settings_obj, name, None)
    if configured is True:
        return True
    if configured is False:
        return False
    raw = environ.get(name)
    return isinstance(raw, str) and raw.strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def _clean_https_origin(value: str) -> bool:
    parts = urlsplit(value)
    return bool(
        parts.scheme == "https"
        and parts.netloc
        and parts.path in ("", "/")
        and not parts.query
        and not parts.fragment
        and not parts.username
        and not parts.password
    )


def _exact_public_url(value: str, expected_path: str) -> bool:
    parts = urlsplit(value)
    return bool(
        parts.scheme == "https"
        and parts.netloc.lower() == CANONICAL_PRODUCTION_HOST
        and parts.path == expected_path
        and not parts.query
        and not parts.fragment
        and not parts.username
        and not parts.password
    )


def _positive_int(value) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value > 0


def inspect_production_runtime_preflight(
    *,
    settings_obj=settings,
    environ: Mapping[str, str] = os.environ,
) -> ProductionRuntimePreflight:
    """Inspect configuration shape only; never open DB/SMTP/S3/network connections."""

    checks: list[ProductionRuntimeCheck] = []

    debug_disabled = getattr(settings_obj, "DEBUG", False) is False
    checks.append(
        _check(
            "debug_disabled",
            "PASS" if debug_disabled else "FAIL",
            "Django debug mode is disabled."
            if debug_disabled
            else "Disable Django debug mode for production.",
        )
    )

    allowed_hosts = getattr(settings_obj, "ALLOWED_HOSTS", ())
    allowed_hosts = (
        tuple(allowed_hosts)
        if isinstance(allowed_hosts, (list, tuple))
        else ()
    )
    allowed_hosts_ready = bool(
        CANONICAL_PRODUCTION_HOST in allowed_hosts
        and "*" not in allowed_hosts
        and allowed_hosts
    )
    checks.append(
        _check(
            "allowed_hosts",
            "PASS" if allowed_hosts_ready else "FAIL",
            "Canonical production host is explicitly allowed."
            if allowed_hosts_ready
            else "Allow the canonical production host explicitly and do not use a wildcard.",
        )
    )

    csrf_cookie_secure = getattr(settings_obj, "CSRF_COOKIE_SECURE", False) is True
    checks.append(
        _check(
            "csrf_cookie_secure",
            "PASS" if csrf_cookie_secure else "FAIL",
            "CSRF cookie requires HTTPS."
            if csrf_cookie_secure
            else "Require HTTPS for the CSRF cookie.",
        )
    )

    session_cookie_secure = (
        getattr(settings_obj, "SESSION_COOKIE_SECURE", False) is True
    )
    checks.append(
        _check(
            "session_cookie_secure",
            "PASS" if session_cookie_secure else "FAIL",
            "Session cookie requires HTTPS."
            if session_cookie_secure
            else "Require HTTPS for the session cookie.",
        )
    )

    site_origin = _environment_or_setting_text(
        settings_obj,
        environ,
        "SITE_ORIGIN",
    )
    site_origin_ready = bool(
        _clean_https_origin(site_origin)
        and site_origin.rstrip("/") == CANONICAL_PRODUCTION_ORIGIN
    )
    checks.append(
        _check(
            "site_origin",
            "PASS" if site_origin_ready else "FAIL",
            "Canonical HTTPS production origin is configured."
            if site_origin_ready
            else "Configure the canonical HTTPS production origin.",
        )
    )

    terms_url = _environment_or_setting_text(
        settings_obj,
        environ,
        "SIGNUP_TERMS_URL",
    )
    terms_ready = _exact_public_url(terms_url, "/terms/")
    checks.append(
        _check(
            "signup_terms_url",
            "PASS" if terms_ready else "FAIL",
            "Terms URL is canonical and same-origin."
            if terms_ready
            else "Configure the canonical same-origin terms URL.",
        )
    )

    privacy_url = _environment_or_setting_text(
        settings_obj,
        environ,
        "SIGNUP_PRIVACY_URL",
    )
    privacy_ready = _exact_public_url(privacy_url, "/privacy/")
    checks.append(
        _check(
            "signup_privacy_url",
            "PASS" if privacy_ready else "FAIL",
            "Privacy URL is canonical and same-origin."
            if privacy_ready
            else "Configure the canonical same-origin privacy URL.",
        )
    )

    terms_version = _setting_or_environment_text(
        settings_obj,
        environ,
        "SIGNUP_TERMS_VERSION",
    ) or DEFAULT_TERMS_VERSION
    privacy_version = _setting_or_environment_text(
        settings_obj,
        environ,
        "SIGNUP_PRIVACY_VERSION",
    ) or DEFAULT_PRIVACY_VERSION
    legal_versions_ready = bool(
        terms_version == DEFAULT_TERMS_VERSION
        and privacy_version == DEFAULT_PRIVACY_VERSION
    )
    checks.append(
        _check(
            "legal_versions",
            "PASS" if legal_versions_ready else "FAIL",
            "Configured legal versions match the code baseline."
            if legal_versions_ready
            else "Configured legal versions must match the finalized code baseline.",
        )
    )

    legal_confirmation_ready = _setting_or_environment_bool(
        settings_obj,
        environ,
        "SIGNUP_LEGAL_DOCUMENTS_CONFIRMED",
    )
    checks.append(
        _check(
            "legal_confirmation",
            "PASS" if legal_confirmation_ready else "FAIL",
            "Legal-document confirmation gate is enabled."
            if legal_confirmation_ready
            else "Legal-document confirmation gate is not enabled.",
        )
    )

    signup_runtime_ready = signup_public_runtime_ready(
        settings_obj=settings_obj,
        environ=environ,
    )
    checks.append(
        _check(
            "signup_runtime",
            "PASS" if signup_runtime_ready else "FAIL",
            "Signup SMTP, verification, and outbox configuration shape is ready."
            if signup_runtime_ready
            else "Signup SMTP, verification, or outbox configuration is incomplete.",
        )
    )

    ssl_redirect_ready = getattr(settings_obj, "SECURE_SSL_REDIRECT", False) is True
    checks.append(
        _check(
            "ssl_redirect",
            "PASS" if ssl_redirect_ready else "WARN",
            "Django HTTPS redirect is enabled."
            if ssl_redirect_ready
            else "Django HTTPS redirect is not enabled; verify the trusted proxy boundary before enabling it.",
        )
    )

    hsts_ready = _positive_int(getattr(settings_obj, "SECURE_HSTS_SECONDS", 0))
    checks.append(
        _check(
            "hsts",
            "PASS" if hsts_ready else "WARN",
            "HSTS is enabled."
            if hsts_ready
            else "HSTS is not enabled; stage it only after production HTTPS is verified.",
        )
    )

    proxy_ssl_header_ready = bool(
        getattr(settings_obj, "SECURE_PROXY_SSL_HEADER", None)
    )
    checks.append(
        _check(
            "proxy_ssl_header",
            "PASS" if proxy_ssl_header_ready else "WARN",
            "A proxy SSL header contract is configured."
            if proxy_ssl_header_ready
            else "No proxy SSL header contract is configured; verify whether TLS terminates before Django.",
        )
    )

    return ProductionRuntimePreflight(checks=tuple(checks))
