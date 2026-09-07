from __future__ import annotations

import datetime as dt
import json
import uuid
from decimal import Decimal
from typing import Any

from django.db import connections, transaction
from psycopg2.extras import Json

from .gpkg import PackageField, _layer_specs
from .layer_plan import allowed_standard_names
from .qgis_sync import (
    SyncConflict,
    SyncOperation,
    SyncRejected,
    _apply_operation,
    _coerce_for_pg,
    _geometry_valid,
    _source_row,
    _uuid_exists,
    sync_runtime_enabled,
)


MAX_CHANGESET_ITEMS = 5000
DEFAULT_DELTA_LIMIT = 1000
MAX_DELTA_LIMIT = 5000
_SYSTEM_FIELDS = {
    "id",
    "project_id",
    "created_at",
    "updated_at",
    "created_by",
    "updated_by",
}


class ChangesetUnavailable(SyncRejected):
    pass


def _uuid_text(value: Any, label: str) -> str:
    try:
        return str(uuid.UUID(str(value)))
    except (ValueError, TypeError, AttributeError) as exc:
        raise SyncRejected(f"{label} must be a valid UUID") from exc


def _plain_value(value: Any, field: PackageField | None = None) -> Any:
    if hasattr(value, "adapted"):
        value = value.adapted
    if value is None or isinstance(value, (str, int, float, bool)):
        if field is not None and str(field.data_type or "").lower() in {"json", "jsonb"} and isinstance(value, str):
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, memoryview):
        return bytes(value).hex()
    if isinstance(value, bytes):
        return value.hex()
    if isinstance(value, dict):
        return {str(key): _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_value(item) for item in value]
    return str(value)


def _decode_geometry_hex(value: Any, *, required: bool, label: str) -> bytes | None:
    if value is None:
        if required:
            raise SyncRejected(f"{label}: geometry_wkb is required")
        return None
    if not isinstance(value, str) or not value.strip():
        raise SyncRejected(f"{label}: geometry_wkb must be a non-empty hex string")
    try:
        raw = bytes.fromhex(value.strip())
    except ValueError as exc:
        raise SyncRejected(f"{label}: geometry_wkb is invalid hex") from exc
    if not raw:
        raise SyncRejected(f"{label}: geometry_wkb is empty")
    return raw


def _support_tables_ready(alias: str) -> bool:
    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            SELECT to_regclass('gis.project_sync_state') IS NOT NULL,
                   to_regclass('gis.changeset_receipt') IS NOT NULL,
                   to_regclass('gis.feature_change_log') IS NOT NULL
            """
        )
        return all(bool(value) for value in cursor.fetchone())


def changeset_runtime_enabled(alias: str) -> bool:
    return sync_runtime_enabled(alias) and _support_tables_ready(alias)


def project_current_revision(alias: str, project_id: str) -> int:
    if not _support_tables_ready(alias):
        return 0
    with connections[alias].cursor() as cursor:
        cursor.execute(
            "SELECT current_revision FROM gis.project_sync_state WHERE project_id=%s",
            [project_id],
        )
        row = cursor.fetchone()
    return int(row[0]) if row else 0


def _ensure_project_state(alias: str, project_id: str) -> int:
    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO gis.project_sync_state(project_id, current_revision, snapshot_revision)
            VALUES (%s, 0, 0)
            ON CONFLICT (project_id) DO NOTHING
            """,
            [project_id],
        )
        cursor.execute(
            "SELECT current_revision FROM gis.project_sync_state WHERE project_id=%s FOR UPDATE",
            [project_id],
        )
        row = cursor.fetchone()
    if row is None:
        raise ChangesetUnavailable("project GIS revision state could not be initialized")
    return int(row[0])


def _field_plain(value: Any, field: PackageField) -> Any:
    return _plain_value(value, field)


def _source_values(source: dict[str, Any], names: list[str], field_by_name: dict[str, PackageField]) -> dict[str, Any]:
    attrs = source.get("attrs") or {}
    return {
        name: _field_plain(attrs.get(name), field_by_name[name])
        for name in names
        if name in field_by_name
    }


def _receipt_replay(alias: str, project_id: str, client_id: str, changeset_id: str) -> dict[str, Any] | None:
    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            SELECT response_payload
              FROM gis.changeset_receipt
             WHERE project_id=%s AND client_id=%s AND changeset_id=%s
            """,
            [project_id, client_id, changeset_id],
        )
        row = cursor.fetchone()
    if not row:
        return None
    payload = row[0] if isinstance(row[0], dict) else json.loads(str(row[0] or "{}"))
    return {**payload, "replayed": True}


def _reserve_receipt(
    alias: str,
    *,
    project_id: str,
    client_id: str,
    changeset_id: str,
    actor_ref: str | None,
    base_revision: int | None,
) -> bool:
    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO gis.changeset_receipt(
                project_id, client_id, changeset_id, actor_ref, base_revision, response_payload
            ) VALUES (%s,%s,%s,%s,%s,'{}'::jsonb)
            ON CONFLICT (project_id, client_id, changeset_id) DO NOTHING
            RETURNING 1
            """,
            [project_id, client_id, changeset_id, actor_ref, base_revision],
        )
        return cursor.fetchone() is not None


def _allocate_revisions(alias: str, project_id: str, count: int) -> tuple[int | None, int | None, int]:
    if count <= 0:
        current = _ensure_project_state(alias, project_id)
        return None, None, current
    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            UPDATE gis.project_sync_state
               SET current_revision=current_revision + %s,
                   updated_at=now()
             WHERE project_id=%s
         RETURNING current_revision
            """,
            [count, project_id],
        )
        row = cursor.fetchone()
    if row is None:
        raise ChangesetUnavailable("project GIS revision allocation failed")
    last_revision = int(row[0])
    first_revision = last_revision - count + 1
    return first_revision, last_revision, last_revision


def _insert_change_log(
    alias: str,
    *,
    project_id: str,
    revision: int,
    changeset_id: str,
    client_id: str,
    standard_name: str,
    physical_name: str,
    object_id: str,
    action: str,
    changed_fields: list[str],
    old_values: dict[str, Any],
    new_values: dict[str, Any],
    geom_before: bytes | None,
    geom_after: bytes | None,
    actor_ref: str | None,
) -> None:
    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            INSERT INTO gis.feature_change_log(
                project_id, revision, changeset_id, client_id,
                standard_name, physical_name, object_id, action,
                changed_fields, old_values, new_values,
                geom_before, geom_after, actor_ref
            ) VALUES (
                %s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,
                ST_GeomFromWKB(%s,4326), ST_GeomFromWKB(%s,4326), %s
            )
            """,
            [
                project_id,
                revision,
                changeset_id,
                client_id,
                standard_name,
                physical_name,
                object_id,
                action,
                Json(changed_fields),
                Json(old_values),
                Json(new_values),
                geom_before,
                geom_after,
                actor_ref,
            ],
        )


def apply_project_changeset(
    alias: str,
    *,
    project_id: str,
    plan: dict[str, Any],
    payload: dict[str, Any],
    actor_ref: str | None = None,
) -> dict[str, Any]:
    if not changeset_runtime_enabled(alias):
        raise ChangesetUnavailable(
            "Changeset API is enabled only in the strict development runtime with GIS revision support installed"
        )
    if not isinstance(payload, dict):
        raise SyncRejected("Changeset payload must be a JSON object")

    client_id = _uuid_text(payload.get("client_id"), "client_id")
    changeset_id = _uuid_text(payload.get("changeset_id"), "changeset_id")
    raw_base_revision = payload.get("base_revision")
    base_revision = None
    if raw_base_revision is not None:
        try:
            base_revision = int(raw_base_revision)
        except (TypeError, ValueError) as exc:
            raise SyncRejected("base_revision must be an integer") from exc
        if base_revision < 0:
            raise SyncRejected("base_revision must be >= 0")

    changes = payload.get("changes")
    if not isinstance(changes, list):
        raise SyncRejected("changes must be a list")
    if len(changes) > MAX_CHANGESET_ITEMS:
        raise SyncRejected(f"Changeset exceeds {MAX_CHANGESET_ITEMS} items")

    specs = _layer_specs(alias, plan)
    allowed = allowed_standard_names(plan)
    by_standard = {spec.standard_name.upper(): spec for spec in specs}
    seen: set[tuple[str, str]] = set()

    with transaction.atomic(using=alias):
        current_before = _ensure_project_state(alias, project_id)
        if base_revision is not None and base_revision > current_before:
            raise SyncRejected(
                f"base_revision {base_revision} is ahead of server revision {current_before}"
            )

        replay = _receipt_replay(alias, project_id, client_id, changeset_id)
        if replay is not None:
            return replay

        if not _reserve_receipt(
            alias,
            project_id=project_id,
            client_id=client_id,
            changeset_id=changeset_id,
            actor_ref=actor_ref,
            base_revision=base_revision,
        ):
            replay = _receipt_replay(alias, project_id, client_id, changeset_id)
            if replay is None:
                raise ChangesetUnavailable("Changeset idempotency receipt is unavailable")
            return replay

        events: list[dict[str, Any]] = []
        counts = {"create": 0, "update": 0, "delete": 0}

        for index, raw_change in enumerate(changes):
            label = f"changes[{index}]"
            if not isinstance(raw_change, dict):
                raise SyncRejected(f"{label} must be an object")
            action = str(raw_change.get("action") or "").lower()
            if action not in {"create", "update", "delete"}:
                raise SyncRejected(f"{label}: unsupported action {action!r}")
            standard_name = str(raw_change.get("layer") or raw_change.get("standard_name") or "").upper()
            if not standard_name or standard_name not in allowed or standard_name not in by_standard:
                raise SyncRejected(f"{label}: layer is outside the active Layer Plan")
            spec = by_standard[standard_name]
            object_id = _uuid_text(raw_change.get("id"), f"{label}.id")
            dedupe_key = (standard_name, object_id)
            if dedupe_key in seen:
                raise SyncRejected(f"{label}: duplicate object in one Changeset")
            seen.add(dedupe_key)

            field_by_name = {field.name: field for field in spec.fields}
            editable_names = {
                field.name
                for field in spec.fields
                if field.editable and field.name not in _SYSTEM_FIELDS
            }
            raw_attributes = raw_change.get("attributes")
            if raw_attributes is None:
                raw_attributes = {}
            if not isinstance(raw_attributes, dict):
                raise SyncRejected(f"{label}.attributes must be an object")
            for name in raw_attributes:
                if name in _SYSTEM_FIELDS or name not in editable_names or name not in field_by_name:
                    raise SyncRejected(f"{label}: protected or unknown field: {name}")

            if action == "create":
                if _uuid_exists(alias, spec.physical_name, object_id, lock=True):
                    raise SyncConflict(
                        [{"layer": standard_name, "id": object_id, "reason": "uuid_already_exists"}]
                    )
                geometry = _decode_geometry_hex(
                    raw_change.get("geometry_wkb"),
                    required=True,
                    label=label,
                )
                if not _geometry_valid(alias, geometry, spec.geometry_kind):
                    raise SyncRejected(f"{label}: invalid geometry")
                attributes = {
                    name: _coerce_for_pg(value, field_by_name[name])
                    for name, value in raw_attributes.items()
                }
                _apply_operation(
                    alias,
                    project_id,
                    SyncOperation(
                        "create",
                        spec.physical_name,
                        standard_name,
                        object_id,
                        attributes,
                        geometry,
                    ),
                )
                after = _source_row(
                    alias,
                    physical_name=spec.physical_name,
                    fields=spec.fields,
                    project_id=project_id,
                    object_id=object_id,
                    lock=True,
                )
                if after is None:
                    raise ChangesetUnavailable(f"{label}: created object could not be re-read")
                full_names = sorted(editable_names)
                new_values = _source_values(after, full_names, field_by_name)
                changed_fields = sorted(set(raw_attributes) | {"geom"})
                events.append(
                    {
                        "action": action,
                        "spec": spec,
                        "id": object_id,
                        "changed_fields": changed_fields,
                        "old_values": {},
                        "new_values": new_values,
                        "geom_before": None,
                        "geom_after": after.get("geom"),
                    }
                )
                counts[action] += 1
                continue

            before = _source_row(
                alias,
                physical_name=spec.physical_name,
                fields=spec.fields,
                project_id=project_id,
                object_id=object_id,
                lock=True,
            )
            if before is None:
                raise SyncConflict(
                    [{"layer": standard_name, "id": object_id, "reason": "server_object_missing"}]
                )

            if action == "delete":
                if raw_attributes or "geometry_wkb" in raw_change:
                    raise SyncRejected(f"{label}: delete must not contain attributes or geometry")
                old_values = _source_values(before, sorted(editable_names), field_by_name)
                _apply_operation(
                    alias,
                    project_id,
                    SyncOperation(
                        "delete",
                        spec.physical_name,
                        standard_name,
                        object_id,
                        {},
                        None,
                    ),
                )
                events.append(
                    {
                        "action": action,
                        "spec": spec,
                        "id": object_id,
                        "changed_fields": ["geom", *sorted(editable_names)],
                        "old_values": old_values,
                        "new_values": {},
                        "geom_before": before.get("geom"),
                        "geom_after": None,
                    }
                )
                counts[action] += 1
                continue

            update_attributes: dict[str, Any] = {}
            old_values: dict[str, Any] = {}
            changed_names: list[str] = []
            for name, raw_value in raw_attributes.items():
                field = field_by_name[name]
                coerced = _coerce_for_pg(raw_value, field)
                new_plain = _field_plain(coerced, field)
                old_plain = _field_plain((before.get("attrs") or {}).get(name), field)
                if new_plain == old_plain:
                    continue
                update_attributes[name] = coerced
                old_values[name] = old_plain
                changed_names.append(name)

            geometry_supplied = "geometry_wkb" in raw_change
            geometry = None
            geometry_changed = False
            if geometry_supplied:
                geometry = _decode_geometry_hex(
                    raw_change.get("geometry_wkb"),
                    required=True,
                    label=label,
                )
                if not _geometry_valid(alias, geometry, spec.geometry_kind):
                    raise SyncRejected(f"{label}: invalid geometry")
                geometry_changed = geometry != before.get("geom")

            if not update_attributes and not geometry_changed:
                continue

            _apply_operation(
                alias,
                project_id,
                SyncOperation(
                    "update",
                    spec.physical_name,
                    standard_name,
                    object_id,
                    update_attributes,
                    geometry if geometry_changed else None,
                ),
            )
            after = _source_row(
                alias,
                physical_name=spec.physical_name,
                fields=spec.fields,
                project_id=project_id,
                object_id=object_id,
                lock=True,
            )
            if after is None:
                raise ChangesetUnavailable(f"{label}: updated object could not be re-read")
            new_values = _source_values(after, changed_names, field_by_name)
            if geometry_changed:
                changed_names.append("geom")
            events.append(
                {
                    "action": action,
                    "spec": spec,
                    "id": object_id,
                    "changed_fields": sorted(changed_names),
                    "old_values": old_values,
                    "new_values": new_values,
                    "geom_before": before.get("geom") if geometry_changed else None,
                    "geom_after": after.get("geom") if geometry_changed else None,
                }
            )
            counts[action] += 1

        first_revision, last_revision, current_revision = _allocate_revisions(
            alias,
            project_id,
            len(events),
        )
        applied: list[dict[str, Any]] = []
        if first_revision is not None:
            for offset, event in enumerate(events):
                revision = first_revision + offset
                spec = event["spec"]
                _insert_change_log(
                    alias,
                    project_id=project_id,
                    revision=revision,
                    changeset_id=changeset_id,
                    client_id=client_id,
                    standard_name=spec.standard_name,
                    physical_name=spec.physical_name,
                    object_id=event["id"],
                    action=event["action"],
                    changed_fields=event["changed_fields"],
                    old_values=event["old_values"],
                    new_values=event["new_values"],
                    geom_before=event["geom_before"],
                    geom_after=event["geom_after"],
                    actor_ref=actor_ref,
                )
                applied.append(
                    {
                        "revision": revision,
                        "action": event["action"],
                        "layer": spec.standard_name,
                        "id": event["id"],
                    }
                )

        response = {
            "ok": True,
            "strategy": "field_patch_last_successful_server_write_wins",
            "project_id": project_id,
            "client_id": client_id,
            "changeset_id": changeset_id,
            "base_revision": base_revision,
            "first_revision": first_revision,
            "last_revision": last_revision,
            "current_revision": current_revision,
            "created": counts["create"],
            "updated": counts["update"],
            "deleted": counts["delete"],
            "total": len(events),
            "applied": applied,
            "replayed": False,
        }
        with connections[alias].cursor() as cursor:
            cursor.execute(
                """
                UPDATE gis.changeset_receipt
                   SET first_revision=%s,
                       last_revision=%s,
                       change_count=%s,
                       response_payload=%s
                 WHERE project_id=%s AND client_id=%s AND changeset_id=%s
                """,
                [
                    first_revision,
                    last_revision,
                    len(events),
                    Json(response),
                    project_id,
                    client_id,
                    changeset_id,
                ],
            )
        return response


def project_delta(
    alias: str,
    *,
    project_id: str,
    since_revision: int,
    limit: int = DEFAULT_DELTA_LIMIT,
) -> dict[str, Any]:
    if not changeset_runtime_enabled(alias):
        raise ChangesetUnavailable(
            "Delta API is enabled only in the strict development runtime with GIS revision support installed"
        )
    try:
        since = int(since_revision)
        page_limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise SyncRejected("since and limit must be integers") from exc
    if since < 0:
        raise SyncRejected("since must be >= 0")
    if page_limit < 1 or page_limit > MAX_DELTA_LIMIT:
        raise SyncRejected(f"limit must be between 1 and {MAX_DELTA_LIMIT}")

    current = project_current_revision(alias, project_id)
    with connections[alias].cursor() as cursor:
        cursor.execute(
            "SELECT min(revision) FROM gis.feature_change_log WHERE project_id=%s",
            [project_id],
        )
        row = cursor.fetchone()
        min_retained = int(row[0]) if row and row[0] is not None else None

    snapshot_required = False
    if since < current:
        if min_retained is None:
            snapshot_required = True
        elif since < min_retained - 1:
            snapshot_required = True

    if snapshot_required:
        return {
            "ok": True,
            "project_id": project_id,
            "since_revision": since,
            "current_revision": current,
            "snapshot_required": True,
            "changes": [],
            "has_more": False,
            "next_revision": since,
        }

    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            SELECT revision, changeset_id, client_id, standard_name, physical_name,
                   object_id, action, changed_fields, new_values,
                   encode(ST_AsBinary(geom_after), 'hex'), created_at
              FROM gis.feature_change_log
             WHERE project_id=%s AND revision>%s
             ORDER BY revision
             LIMIT %s
            """,
            [project_id, since, page_limit + 1],
        )
        rows = cursor.fetchall()

    has_more = len(rows) > page_limit
    rows = rows[:page_limit]
    changes = []
    for row in rows:
        changed_fields = row[7] if isinstance(row[7], list) else json.loads(str(row[7] or "[]"))
        new_values = row[8] if isinstance(row[8], dict) else json.loads(str(row[8] or "{}"))
        changes.append(
            {
                "revision": int(row[0]),
                "changeset_id": str(row[1]),
                "client_id": str(row[2]),
                "layer": str(row[3]),
                "physical_name": str(row[4]),
                "id": str(row[5]),
                "action": str(row[6]),
                "changed_fields": changed_fields,
                "attributes": new_values,
                "geometry_wkb": row[9] or None,
                "created_at": row[10].isoformat() if row[10] else None,
            }
        )
    next_revision = int(changes[-1]["revision"]) if changes else since
    return {
        "ok": True,
        "project_id": project_id,
        "since_revision": since,
        "current_revision": current,
        "snapshot_required": False,
        "changes": changes,
        "has_more": has_more,
        "next_revision": next_revision,
    }
