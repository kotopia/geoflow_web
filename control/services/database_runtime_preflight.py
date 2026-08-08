from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass

from django.conf import settings


ENCRYPTED_POSTGRES_SSLMODES = {"require", "verify-ca", "verify-full"}


@dataclass(frozen=True)
class DatabaseRuntimeCheck:
    code: str
    ready: bool
    message: str


def _present(environ: Mapping[str, str], name: str) -> bool:
    return bool(str(environ.get(name) or "").strip())


def _valid_port(environ: Mapping[str, str], name: str) -> bool:
    raw = str(environ.get(name) or "").strip()
    try:
        value = int(raw)
    except ValueError:
        return False
    return 1 <= value <= 65535


def _nonlocal_host(environ: Mapping[str, str], name: str) -> bool:
    host = str(environ.get(name) or "").strip().lower()
    return bool(host and host not in {"localhost", "127.0.0.1", "::1"})


def _enabled(environ: Mapping[str, str], name: str) -> bool:
    return str(environ.get(name) or "").strip().lower() in {
        "1",
        "true",
        "yes",
        "y",
        "on",
    }


def _database_transport_ready(settings_obj) -> bool:
    databases = getattr(settings_obj, "DATABASES", None)
    if not isinstance(databases, dict) or not databases:
        return False

    postgres_seen = False
    for config in databases.values():
        if not isinstance(config, dict):
            continue
        engine = str(config.get("ENGINE") or "").lower()
        if "postgresql" not in engine and "postgis" not in engine:
            continue
        postgres_seen = True
        options = config.get("OPTIONS")
        if not isinstance(options, dict):
            return False
        sslmode = str(options.get("sslmode") or "").strip().lower()
        if sslmode not in ENCRYPTED_POSTGRES_SSLMODES:
            return False
    return postgres_seen


def inspect_database_runtime(
    *,
    settings_obj=settings,
    environ: Mapping[str, str] = os.environ,
) -> tuple[DatabaseRuntimeCheck, ...]:
    """Inspect DB configuration shape only; never open a database connection."""

    checks: list[DatabaseRuntimeCheck] = []

    for prefix, label in (("CENTRAL_DB", "central"), ("TENANT_DB", "tenant")):
        required = ("NAME", "USER", "PASSWORD", "HOST")
        explicit = all(_present(environ, f"{prefix}_{suffix}") for suffix in required)
        checks.append(
            DatabaseRuntimeCheck(
                code=f"{label}_db_explicit_credentials",
                ready=explicit,
                message=(
                    f"Production {label} database configuration is explicit."
                    if explicit
                    else f"Configure explicit production {label} database name, user, password, and host; do not rely on fallback credentials."
                ),
            )
        )

        host_ready = _nonlocal_host(environ, f"{prefix}_HOST")
        checks.append(
            DatabaseRuntimeCheck(
                code=f"{label}_db_nonlocal_host",
                ready=host_ready,
                message=(
                    f"Production {label} database host is non-local."
                    if host_ready
                    else f"Production {label} database must not use a local host fallback."
                ),
            )
        )

        port_ready = _valid_port(environ, f"{prefix}_PORT")
        checks.append(
            DatabaseRuntimeCheck(
                code=f"{label}_db_port",
                ready=port_ready,
                message=(
                    f"Production {label} database port is explicitly valid."
                    if port_ready
                    else f"Configure an explicit valid production {label} database port."
                ),
            )
        )

    provisioning_disabled = not _enabled(environ, "ENABLE_TENANT_PROVISIONING")
    checks.append(
        DatabaseRuntimeCheck(
            code="tenant_provisioning_disabled",
            ready=provisioning_disabled,
            message=(
                "Tenant provisioning is disabled in the application runtime."
                if provisioning_disabled
                else "Disable tenant provisioning in the public application runtime before release."
            ),
        )
    )

    transport_ready = _database_transport_ready(settings_obj)
    checks.append(
        DatabaseRuntimeCheck(
            code="database_transport_tls",
            ready=transport_ready,
            message=(
                "Configured PostgreSQL/PostGIS connections require encrypted transport."
                if transport_ready
                else "Require PostgreSQL/PostGIS sslmode=require, verify-ca, or verify-full for every configured database."
            ),
        )
    )

    return tuple(checks)
