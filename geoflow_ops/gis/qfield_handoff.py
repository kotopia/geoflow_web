from __future__ import annotations

import hashlib

from django.core.cache import cache

from .qfield_auth import QFIELD_HANDOFF_MAX_AGE_SECONDS


_PENDING_PREFIX = "geoflow:qfield:pending-handoff:v1"


def _pending_key(*, project_id: str, user_id: str, group_id: str, install_id: str) -> str:
    raw = "|".join(
        [
            str(project_id),
            str(user_id),
            str(group_id),
            str(install_id),
        ]
    )
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()
    return f"{_PENDING_PREFIX}:{digest}"


def stage_pending_handoff(
    *,
    project_id: str,
    user_id: str,
    group_id: str,
    install_id: str,
    handoff_token: str,
) -> None:
    """Stage one browser-authorized handoff for the already-installed project.

    This cache entry is intentionally short lived. The install claim credential
    stored in QField cannot create this entry; it can only consume a matching
    entry after the user authenticated in GeoFlow and pressed QField open.
    """

    cache.set(
        _pending_key(
            project_id=project_id,
            user_id=user_id,
            group_id=group_id,
            install_id=install_id,
        ),
        str(handoff_token),
        timeout=QFIELD_HANDOFF_MAX_AGE_SECONDS,
    )


def consume_pending_handoff(
    *,
    project_id: str,
    user_id: str,
    group_id: str,
    install_id: str,
) -> str:
    """Atomically consume a pending handoff as far as the cache backend allows."""

    key = _pending_key(
        project_id=project_id,
        user_id=user_id,
        group_id=group_id,
        install_id=install_id,
    )
    token = cache.get(key)
    if token:
        cache.delete(key)
    return str(token or "")
