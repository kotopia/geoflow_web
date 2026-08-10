from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .env_values import get_optional_env_int


_TRUE_VALUES = {"1", "true", "yes", "y", "on"}
_FALSE_VALUES = {"0", "false", "no", "n", "off"}
EXPECTED_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
MAX_HSTS_SECONDS = 2 * 365 * 24 * 60 * 60
PRELOAD_MINIMUM_SECONDS = 365 * 24 * 60 * 60


@dataclass(frozen=True)
class ProxySecuritySettings:
    proxy_ssl_header: tuple[str, str] | None
    ssl_redirect: bool
    hsts_seconds: int
    hsts_include_subdomains: bool
    hsts_preload: bool


def _strict_bool(
    environ: Mapping[str, str],
    name: str,
    *,
    default: bool,
) -> bool:
    raw = environ.get(name)
    if raw is None or str(raw).strip() == "":
        return default
    value = str(raw).strip().lower()
    if value in _TRUE_VALUES:
        return True
    if value in _FALSE_VALUES:
        return False
    raise RuntimeError(f"Invalid boolean environment variable: {name}")


def load_proxy_security_settings(
    environ: Mapping[str, str],
) -> ProxySecuritySettings:
    """Load the trusted-proxy/TLS settings with fail-closed validation.

    The proxy header contract is intentionally not configurable as arbitrary text:
    enabling it always means exactly ``HTTP_X_FORWARDED_PROTO=https``.
    """

    trust_forwarded_proto = _strict_bool(
        environ,
        "DJANGO_TRUST_X_FORWARDED_PROTO",
        default=False,
    )
    ssl_redirect = _strict_bool(
        environ,
        "DJANGO_SECURE_SSL_REDIRECT",
        default=False,
    )
    hsts_seconds = get_optional_env_int(
        environ,
        "DJANGO_SECURE_HSTS_SECONDS",
        minimum=0,
        maximum=MAX_HSTS_SECONDS,
    )
    if hsts_seconds is None:
        hsts_seconds = 0
    hsts_include_subdomains = _strict_bool(
        environ,
        "DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS",
        default=False,
    )
    hsts_preload = _strict_bool(
        environ,
        "DJANGO_SECURE_HSTS_PRELOAD",
        default=False,
    )

    if hsts_seconds == 0 and (hsts_include_subdomains or hsts_preload):
        raise RuntimeError(
            "HSTS subdomain/preload flags require DJANGO_SECURE_HSTS_SECONDS > 0"
        )
    if hsts_preload and (
        not hsts_include_subdomains or hsts_seconds < PRELOAD_MINIMUM_SECONDS
    ):
        raise RuntimeError(
            "HSTS preload requires includeSubDomains and at least one year of HSTS"
        )

    return ProxySecuritySettings(
        proxy_ssl_header=(EXPECTED_PROXY_SSL_HEADER if trust_forwarded_proto else None),
        ssl_redirect=ssl_redirect,
        hsts_seconds=hsts_seconds,
        hsts_include_subdomains=hsts_include_subdomains,
        hsts_preload=hsts_preload,
    )
