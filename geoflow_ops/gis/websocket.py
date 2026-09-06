from __future__ import annotations

import logging
import uuid
from types import SimpleNamespace

from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer
from django.conf import settings
from django.db import connections

from control.gf_authz.permissions import gf_has_perm
from geoflow_ops.models import Project
from geoflow_ops.services.project_access import project_access_policy

from .events import project_group_name, realtime_runtime_enabled
from .realtime_auth import bearer_token_from_headers, parse_realtime_ticket


logger = logging.getLogger(__name__)


class ProjectGISConsumer(AsyncJsonWebsocketConsumer):
    async def connect(self):
        if not realtime_runtime_enabled():
            await self.close(code=4403)
            return

        raw_project_id = (self.scope.get("url_route") or {}).get("kwargs", {}).get("project_id")
        try:
            project_id = str(uuid.UUID(str(raw_project_id)))
        except (TypeError, ValueError, AttributeError):
            await self.close(code=4400)
            return

        # Desktop QGIS authenticates the WebSocket with a short-lived signed
        # ticket issued over its already-authenticated HTTP session.  This
        # avoids relying on QtWebSocket to reproduce Django's browser cookie
        # semantics.  Browser WebGIS keeps the normal session-cookie path.
        token = bearer_token_from_headers(self.scope.get("headers"))
        ticket = parse_realtime_ticket(token, project_id=project_id) if token else None
        if ticket is not None:
            alias = str(ticket.get("alias") or "")
            if (
                not alias
                or alias == getattr(settings, "CENTRAL_DB_ALIAS", "default")
                or not await self._ticket_project_exists(alias=alias, project_id=project_id)
            ):
                logger.warning(
                    "DEV-GIS-WS reject ticket project_id=%s alias=%s reason=invalid_scope",
                    project_id,
                    alias,
                )
                await self.close(code=4403)
                return
            await self._accept_project(project_id)
            return

        user = self.scope.get("user")
        if not user or not getattr(user, "is_authenticated", False):
            logger.warning(
                "DEV-GIS-WS reject session project_id=%s reason=anonymous",
                project_id,
            )
            await self.close(code=4401)
            return

        session = self.scope.get("session")
        alias = str(session.get("tenant_db_alias") or "") if session is not None else ""
        if not alias or alias == getattr(settings, "CENTRAL_DB_ALIAS", "default"):
            logger.warning(
                "DEV-GIS-WS reject session project_id=%s reason=tenant_alias alias=%s",
                project_id,
                alias,
            )
            await self.close(code=4403)
            return

        session_values = dict(session.items()) if session is not None else {}
        authorized = await self._authorized(
            alias=alias,
            project_id=project_id,
            user=user,
            session_values=session_values,
        )
        if not authorized:
            logger.warning(
                "DEV-GIS-WS reject session project_id=%s alias=%s reason=project_policy",
                project_id,
                alias,
            )
            await self.close(code=4403)
            return

        await self._accept_project(project_id)

    async def _accept_project(self, project_id: str) -> None:
        self.project_id = project_id
        self.group_name = project_group_name(project_id)
        await self.channel_layer.group_add(self.group_name, self.channel_name)
        await self.accept()
        await self.send_json(
            {
                "type": "gis.realtime.ready",
                "project_id": project_id,
            }
        )

    async def disconnect(self, close_code):
        group_name = getattr(self, "group_name", None)
        if group_name and self.channel_layer is not None:
            await self.channel_layer.group_discard(group_name, self.channel_name)

    async def gis_project_change(self, event):
        payload = event.get("payload") or {}
        if str(payload.get("project_id") or "") != getattr(self, "project_id", ""):
            return
        await self.send_json(payload)

    @database_sync_to_async
    def _ticket_project_exists(self, *, alias: str, project_id: str) -> bool:
        if alias not in connections.databases:
            return False
        return Project.objects.using(alias).filter(pk=project_id).exists()

    @database_sync_to_async
    def _authorized(self, *, alias: str, project_id: str, user, session_values: dict) -> bool:
        if alias not in connections.databases:
            return False

        request = SimpleNamespace(user=user, session=session_values)
        request._gf_perms_cache = set(session_values.get("gf_perms") or [])
        request._gf_roles_cache = set(session_values.get("gf_roles") or [])

        if not gf_has_perm(request, "maps.view"):
            return False
        if not Project.objects.using(alias).filter(pk=project_id).exists():
            return False
        policy = project_access_policy(request, alias)
        return bool(policy.can_webgis_read(project_id))
