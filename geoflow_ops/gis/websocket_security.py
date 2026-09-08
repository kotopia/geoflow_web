from __future__ import annotations

import re

from channels.security.websocket import AllowedHostsOriginValidator

from .realtime_auth import (
    bearer_token_from_headers,
    parse_realtime_ticket,
    ticket_token_from_query_string,
)


_PROJECT_WS_RE = re.compile(
    r"^/ws/gis/projects/(?P<project_id>[0-9a-fA-F-]{36})/$"
)


def scope_has_valid_realtime_ticket(scope) -> bool:
    """Return True only for a valid signed GeoFlow QGIS WebSocket ticket.

    Browser WebGIS sockets continue to require the normal Origin/ALLOWED_HOSTS
    validation. Native QGIS is not a browser and Qt can emit an Origin that the
    browser-focused Channels validator rejects. A short-lived, project-scoped
    server-signed ticket is therefore sufficient to bypass only that outer
    Origin check; the consumer still performs its own ticket/project/tenant
    validation before accepting the socket.
    """

    if str(scope.get("type") or "") != "websocket":
        return False
    match = _PROJECT_WS_RE.fullmatch(str(scope.get("path") or ""))
    if match is None:
        return False

    token = bearer_token_from_headers(scope.get("headers"))
    if not token:
        token = ticket_token_from_query_string(scope.get("query_string"))
    if not token:
        return False

    return (
        parse_realtime_ticket(
            token,
            project_id=match.group("project_id"),
        )
        is not None
    )


class TicketAwareAllowedHostsOriginValidator:
    """Use browser Origin validation unless a valid QGIS ticket is present."""

    def __init__(self, application):
        self.application = application
        self.origin_validator = AllowedHostsOriginValidator(application)

    async def __call__(self, scope, receive, send):
        if scope_has_valid_realtime_ticket(scope):
            return await self.application(scope, receive, send)
        return await self.origin_validator(scope, receive, send)
