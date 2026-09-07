from __future__ import annotations

import logging
import os
import uuid
from typing import Any

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer
from django.conf import settings


logger = logging.getLogger(__name__)


def realtime_runtime_enabled() -> bool:
    return bool(
        settings.DEBUG
        and os.getenv("GEOFLOW_DEV_RUNTIME_STRICT") == "1"
    )


def project_group_name(project_id: str) -> str:
    normalized = uuid.UUID(str(project_id))
    return f"gis.project.{normalized.hex}"


def build_project_change_event(result: dict[str, Any]) -> dict[str, Any] | None:
    applied = result.get("applied") or []
    if not applied:
        return None

    changes = []
    for row in applied:
        changes.append(
            {
                "revision": int(row.get("revision") or 0),
                "action": str(row.get("action") or ""),
                "layer": str(row.get("layer") or ""),
                "id": str(uuid.UUID(str(row.get("id")))),
            }
        )

    return {
        "type": "gis.project.change",
        "project_id": str(uuid.UUID(str(result.get("project_id")))),
        "current_revision": int(result.get("current_revision") or 0),
        "client_id": str(result.get("client_id") or ""),
        "changeset_id": str(result.get("changeset_id") or ""),
        "changes": changes,
    }


def publish_project_change_event(result: dict[str, Any]) -> bool:
    """Best-effort dev WebSocket notification after a committed Changeset.

    Persistence never depends on delivery of the realtime hint. Clients can
    always recover from missed notifications using the revision/Delta API.
    """
    if not realtime_runtime_enabled():
        return False
    event = build_project_change_event(result)
    if event is None:
        return False
    channel_layer = get_channel_layer()
    if channel_layer is None:
        return False

    try:
        async_to_sync(channel_layer.group_send)(
            project_group_name(event["project_id"]),
            {
                "type": "gis_project_change",
                "payload": event,
            },
        )
    except Exception:
        logger.exception(
            "DEV-GIS-REALTIME publish failed project_id=%s revision=%s",
            event["project_id"],
            event["current_revision"],
        )
        return False
    return True
