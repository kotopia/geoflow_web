from __future__ import annotations

import uuid
from typing import Any

from django.core import signing


TICKET_SALT = "geoflow.gis.realtime.ticket.v1"
TICKET_MAX_AGE_SECONDS = 90


def issue_realtime_ticket(*, project_id: str, alias: str, user_id: Any) -> str:
    payload = {
        "project_id": str(uuid.UUID(str(project_id))),
        "alias": str(alias),
        "user_id": str(user_id),
    }
    return signing.dumps(payload, salt=TICKET_SALT, compress=True)


def parse_realtime_ticket(token: str, *, project_id: str) -> dict[str, str] | None:
    if not token:
        return None
    try:
        payload = signing.loads(
            token,
            salt=TICKET_SALT,
            max_age=TICKET_MAX_AGE_SECONDS,
        )
    except (signing.BadSignature, signing.SignatureExpired):
        return None
    if not isinstance(payload, dict):
        return None
    try:
        expected_project = str(uuid.UUID(str(project_id)))
        ticket_project = str(uuid.UUID(str(payload.get("project_id"))))
    except (TypeError, ValueError, AttributeError):
        return None
    if ticket_project != expected_project:
        return None
    alias = str(payload.get("alias") or "")
    user_id = str(payload.get("user_id") or "")
    if not alias or not user_id:
        return None
    return {
        "project_id": ticket_project,
        "alias": alias,
        "user_id": user_id,
    }


def bearer_token_from_headers(headers) -> str:
    for name, value in headers or []:
        try:
            header_name = bytes(name).decode("latin1").lower()
            header_value = bytes(value).decode("latin1")
        except Exception:
            continue
        if header_name != "authorization":
            continue
        prefix = "bearer "
        if header_value.lower().startswith(prefix):
            return header_value[len(prefix):].strip()
    return ""
