from __future__ import annotations

import uuid
from decimal import Decimal, InvalidOperation
from typing import Any

from django.db import connections, transaction
from psycopg2.extras import Json

from .changeset import (
    MAX_CHANGESET_ITEMS,
    ChangesetUnavailable,
    _allocate_revisions,
    _ensure_project_state,
    _insert_change_log,
    _receipt_replay,
    _reserve_receipt,
    _uuid_text,
    changeset_runtime_enabled,
)
from .layer_plan import allowed_standard_names
from .qgis_sync import SyncConflict, SyncRejected, _quote_ident


SURVEY_LINK_STANDARD_NAME = "SURVEY_LINK"
SURVEY_LINK_PHYSICAL_NAME = "survey_link"
SURVEY_LINK_RESOURCE_KIND = "relation"
MATCH_METHODS = frozenset({"manual", "nearest", "code", "import", "gnss"})


def _optional_decimal(
    value: Any,
    *,
    field: str,
    minimum: Decimal | None = None,
    maximum: Decimal | None = None,
) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        result = Decimal(str(value).strip())
    except (InvalidOperation, ValueError, TypeError) as exc:
        raise SyncRejected(f"{field}: invalid number") from exc
    if not result.is_finite() or (minimum is not None and result < minimum) or (
        maximum is not None and result > maximum
    ):
        raise SyncRejected(f"{field}: value is outside the allowed range")
    return result


def _feature_type_for_layer(
    alias: str,
    *,
    plan: dict[str, Any],
    standard_name: str,
) -> dict[str, str]:
    standard = str(standard_name or "").strip().upper()
    if not standard or standard == "SURVEY" or standard not in allowed_standard_names(plan):
        raise SyncRejected("layer is outside the active Layer Plan or is not a facility layer")
    with connections[alias].cursor() as cursor:
        cursor.execute(
            """
            SELECT id::text, standard_name, physical_name, feature_role
              FROM gis.meta_feature_type
             WHERE upper(standard_name)=upper(%s) AND active=true
            """,
            [standard],
        )
        row = cursor.fetchone()
    if row is None:
        raise SyncRejected("layer is not registered in GIS metadata")
    if str(row[3] or "").upper() != "ASSET":
        raise SyncRejected("layer is not an asset feature type")
    physical_name = str(row[2])
    _quote_ident(physical_name)
    return {
        "id": str(row[0]),
        "standard_name": str(row[1]).upper(),
        "physical_name": physical_name,
    }


def _survey_exists(alias: str, *, project_id: str, survey_id: str, lock: bool) -> bool:
    suffix = " FOR UPDATE" if lock else ""
    with connections[alias].cursor() as cursor:
        cursor.execute(
            f"SELECT 1 FROM gis.survey WHERE project_id=%s AND id=%s{suffix}",
            [project_id, survey_id],
        )
        return cursor.fetchone() is not None


def _target_exists(
    alias: str,
    *,
    project_id: str,
    physical_name: str,
    target_id: str,
    lock: bool,
) -> bool:
    table = _quote_ident(physical_name)
    suffix = " FOR UPDATE" if lock else ""
    with connections[alias].cursor() as cursor:
        cursor.execute(
            f'SELECT 1 FROM "gis".{table} WHERE project_id=%s AND id=%s{suffix}',
            [project_id, target_id],
        )
        return cursor.fetchone() is not None


def _link_by_id(alias: str, *, project_id: str, link_id: str, lock: bool) -> dict[str, Any] | None:
    suffix = " FOR UPDATE OF sl" if lock else ""
    with connections[alias].cursor() as cursor:
        cursor.execute(
            f"""
            SELECT sl.id::text, sl.survey_id::text, sl.feature_type_id::text,
                   ft.standard_name, ft.physical_name, sl.target_id::text,
                   sl.match_method, sl.match_distance, sl.match_confidence,
                   sl.confirmed_by::text, sl.confirmed_at, sl.created_at
              FROM gis.survey_link sl
              JOIN gis.survey s ON s.id=sl.survey_id
              JOIN gis.meta_feature_type ft ON ft.id=sl.feature_type_id
             WHERE s.project_id=%s AND sl.id=%s{suffix}
            """,
            [project_id, link_id],
        )
        row = cursor.fetchone()
    if row is None:
        return None
    return {
        "id": str(row[0]),
        "survey_id": str(row[1]),
        "feature_type_id": str(row[2]),
        "layer": str(row[3]).upper(),
        "physical_name": str(row[4]),
        "target_id": str(row[5]),
        "match_method": str(row[6]),
        "match_distance": float(row[7]) if row[7] is not None else None,
        "match_confidence": float(row[8]) if row[8] is not None else None,
        "confirmed_by": str(row[9]) if row[9] is not None else None,
        "confirmed_at": row[10].isoformat() if row[10] is not None else None,
        "created_at": row[11].isoformat() if row[11] is not None else None,
    }


def _relation_values(row: dict[str, Any]) -> dict[str, Any]:
    return {
        key: row.get(key)
        for key in (
            "survey_id",
            "feature_type_id",
            "layer",
            "physical_name",
            "target_id",
            "match_method",
            "match_distance",
            "match_confidence",
            "confirmed_by",
            "confirmed_at",
        )
    }


def apply_survey_link_changeset(
    alias: str,
    *,
    project_id: str,
    plan: dict[str, Any],
    payload: dict[str, Any],
    actor_ref: str | None = None,
) -> dict[str, Any]:
    if not changeset_runtime_enabled(alias):
        raise ChangesetUnavailable("Survey-link Changeset is unavailable in this runtime")
    if not isinstance(payload, dict):
        raise SyncRejected("Changeset payload must be a JSON object")

    client_id = _uuid_text(payload.get("client_id"), "client_id")
    changeset_id = _uuid_text(payload.get("changeset_id"), "changeset_id")
    raw_base_revision = payload.get("base_revision")
    try:
        base_revision = None if raw_base_revision is None else int(raw_base_revision)
    except (TypeError, ValueError) as exc:
        raise SyncRejected("base_revision must be an integer") from exc
    if base_revision is not None and base_revision < 0:
        raise SyncRejected("base_revision must be >= 0")

    changes = payload.get("changes")
    if not isinstance(changes, list):
        raise SyncRejected("changes must be a list")
    if len(changes) > MAX_CHANGESET_ITEMS:
        raise SyncRejected(f"Changeset exceeds {MAX_CHANGESET_ITEMS} items")

    seen: set[str] = set()
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
        counts = {"create": 0, "delete": 0}
        for index, raw in enumerate(changes):
            label = f"changes[{index}]"
            if not isinstance(raw, dict):
                raise SyncRejected(f"{label} must be an object")
            action = str(raw.get("action") or "").lower()
            if action not in {"create", "delete"}:
                raise SyncRejected(f"{label}: survey links support create or delete only")
            link_id = _uuid_text(raw.get("id"), f"{label}.id")
            if link_id in seen:
                raise SyncRejected(f"{label}: duplicate link id in one Changeset")
            seen.add(link_id)

            if action == "delete":
                unexpected = set(raw) - {"action", "id"}
                if unexpected:
                    raise SyncRejected(f"{label}: delete must contain only action and id")
                before = _link_by_id(alias, project_id=project_id, link_id=link_id, lock=True)
                if before is None:
                    raise SyncConflict(
                        [{"resource_kind": SURVEY_LINK_RESOURCE_KIND, "id": link_id, "reason": "server_link_missing"}]
                    )
                with connections[alias].cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM gis.survey_link WHERE id=%s",
                        [link_id],
                    )
                    if cursor.rowcount != 1:
                        raise SyncConflict(
                            [{"resource_kind": SURVEY_LINK_RESOURCE_KIND, "id": link_id, "reason": "delete_target_changed"}]
                        )
                events.append({"action": action, "id": link_id, "old": _relation_values(before), "new": {}})
                counts[action] += 1
                continue

            allowed_keys = {
                "action", "id", "survey_id", "layer", "standard_name", "target_id",
                "match_method", "match_distance", "match_confidence",
            }
            unexpected = set(raw) - allowed_keys
            if unexpected:
                raise SyncRejected(f"{label}: unknown field: {sorted(unexpected)[0]}")
            survey_id = _uuid_text(raw.get("survey_id"), f"{label}.survey_id")
            target_id = _uuid_text(raw.get("target_id"), f"{label}.target_id")
            feature_type = _feature_type_for_layer(
                alias,
                plan=plan,
                standard_name=raw.get("layer") or raw.get("standard_name"),
            )
            match_method = str(raw.get("match_method") or "").strip().lower()
            if match_method not in MATCH_METHODS:
                raise SyncRejected(
                    f"{label}.match_method must be one of: {', '.join(sorted(MATCH_METHODS))}"
                )
            match_distance = _optional_decimal(
                raw.get("match_distance"), field=f"{label}.match_distance", minimum=Decimal("0")
            )
            match_confidence = _optional_decimal(
                raw.get("match_confidence"),
                field=f"{label}.match_confidence",
                minimum=Decimal("0"),
                maximum=Decimal("1"),
            )
            if not _survey_exists(alias, project_id=project_id, survey_id=survey_id, lock=True):
                raise SyncConflict(
                    [{"resource_kind": SURVEY_LINK_RESOURCE_KIND, "id": link_id, "reason": "survey_outside_project_or_missing"}]
                )
            if not _target_exists(
                alias,
                project_id=project_id,
                physical_name=feature_type["physical_name"],
                target_id=target_id,
                lock=True,
            ):
                raise SyncConflict(
                    [{"resource_kind": SURVEY_LINK_RESOURCE_KIND, "id": link_id, "reason": "target_outside_project_or_missing"}]
                )
            with connections[alias].cursor() as cursor:
                cursor.execute(
                    "SELECT id::text FROM gis.survey_link WHERE id=%s OR "
                    "(survey_id=%s AND feature_type_id=%s AND target_id=%s)",
                    [link_id, survey_id, feature_type["id"], target_id],
                )
                duplicate = cursor.fetchone()
            if duplicate is not None:
                reason = "link_id_already_exists" if str(duplicate[0]) == link_id else "relation_already_exists"
                raise SyncConflict(
                    [{"resource_kind": SURVEY_LINK_RESOURCE_KIND, "id": link_id, "reason": reason}]
                )

            confirmed_by = None
            try:
                confirmed_by = str(uuid.UUID(str(actor_ref))) if actor_ref else None
            except (ValueError, TypeError, AttributeError):
                confirmed_by = None
            with connections[alias].cursor() as cursor:
                cursor.execute(
                    """
                    INSERT INTO gis.survey_link(
                        id, survey_id, feature_type_id, target_id, match_method,
                        match_distance, match_confidence, confirmed_by, confirmed_at
                    ) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,now())
                    """,
                    [
                        link_id, survey_id, feature_type["id"], target_id, match_method,
                        match_distance, match_confidence, confirmed_by,
                    ],
                )
            after = _link_by_id(alias, project_id=project_id, link_id=link_id, lock=True)
            if after is None:
                raise ChangesetUnavailable(f"{label}: created link could not be re-read")
            events.append({"action": action, "id": link_id, "old": {}, "new": _relation_values(after)})
            counts[action] += 1

        first_revision, last_revision, current_revision = _allocate_revisions(
            alias, project_id, len(events)
        )
        applied = []
        if first_revision is not None:
            for offset, event in enumerate(events):
                revision = first_revision + offset
                values = event["new"] or event["old"]
                _insert_change_log(
                    alias,
                    project_id=project_id,
                    revision=revision,
                    changeset_id=changeset_id,
                    client_id=client_id,
                    standard_name=SURVEY_LINK_STANDARD_NAME,
                    physical_name=SURVEY_LINK_PHYSICAL_NAME,
                    object_id=event["id"],
                    action=event["action"],
                    changed_fields=sorted(values),
                    old_values=event["old"],
                    new_values=event["new"],
                    geom_before=None,
                    geom_after=None,
                    actor_ref=actor_ref,
                )
                applied.append(
                    {
                        "revision": revision,
                        "resource_kind": SURVEY_LINK_RESOURCE_KIND,
                        "action": event["action"],
                        "layer": SURVEY_LINK_STANDARD_NAME,
                        "id": event["id"],
                    }
                )

        response = {
            "ok": True,
            "protocol": "survey_link_changeset_v1",
            "resource_kind": SURVEY_LINK_RESOURCE_KIND,
            "project_id": project_id,
            "client_id": client_id,
            "changeset_id": changeset_id,
            "base_revision": base_revision,
            "first_revision": first_revision,
            "last_revision": last_revision,
            "current_revision": current_revision,
            "created": counts["create"],
            "deleted": counts["delete"],
            "total": len(events),
            "applied": applied,
            "replayed": False,
        }
        with connections[alias].cursor() as cursor:
            cursor.execute(
                """
                UPDATE gis.changeset_receipt
                   SET first_revision=%s, last_revision=%s, change_count=%s,
                       response_payload=%s
                 WHERE project_id=%s AND client_id=%s AND changeset_id=%s
                """,
                [
                    first_revision, last_revision, len(events), Json(response),
                    project_id, client_id, changeset_id,
                ],
            )
        return response


def list_survey_links(
    alias: str,
    *,
    project_id: str,
    plan: dict[str, Any],
    survey_id: str | None = None,
    standard_name: str | None = None,
    target_id: str | None = None,
    limit: int = 1000,
) -> list[dict[str, Any]]:
    try:
        page_limit = int(limit)
    except (TypeError, ValueError) as exc:
        raise SyncRejected("limit must be an integer") from exc
    if page_limit < 1 or page_limit > 5000:
        raise SyncRejected("limit must be between 1 and 5000")
    permitted_layers = sorted(
        standard
        for standard in allowed_standard_names(plan)
        if str(standard).upper() != "SURVEY"
    )
    if not permitted_layers:
        return []
    requested_layer = str(standard_name or "").strip().upper()
    if requested_layer and requested_layer not in permitted_layers:
        raise SyncRejected("layer is outside the active Layer Plan")

    params: list[Any] = [project_id, permitted_layers]
    filters = ["s.project_id=%s"]
    filters.append("upper(ft.standard_name)=ANY(%s)")
    if survey_id:
        filters.append("sl.survey_id=%s")
        params.append(_uuid_text(survey_id, "survey_id"))
    if requested_layer:
        filters.append("upper(ft.standard_name)=upper(%s)")
        params.append(requested_layer)
    if target_id:
        filters.append("sl.target_id=%s")
        params.append(_uuid_text(target_id, "target_id"))
    params.append(page_limit)
    with connections[alias].cursor() as cursor:
        cursor.execute(
            f"""
            SELECT sl.id::text, sl.survey_id::text, sl.feature_type_id::text,
                   ft.standard_name, ft.physical_name, sl.target_id::text,
                   sl.match_method, sl.match_distance, sl.match_confidence,
                   sl.confirmed_by::text, sl.confirmed_at, sl.created_at
              FROM gis.survey_link sl
              JOIN gis.survey s ON s.id=sl.survey_id
              JOIN gis.meta_feature_type ft ON ft.id=sl.feature_type_id
             WHERE {' AND '.join(filters)}
             ORDER BY sl.created_at, sl.id
             LIMIT %s
            """,
            params,
        )
        rows = cursor.fetchall()
    result = []
    for row in rows:
        result.append(
            {
                "id": str(row[0]), "survey_id": str(row[1]), "feature_type_id": str(row[2]),
                "layer": str(row[3]).upper(), "physical_name": str(row[4]), "target_id": str(row[5]),
                "match_method": str(row[6]),
                "match_distance": float(row[7]) if row[7] is not None else None,
                "match_confidence": float(row[8]) if row[8] is not None else None,
                "confirmed_by": str(row[9]) if row[9] is not None else None,
                "confirmed_at": row[10].isoformat() if row[10] is not None else None,
                "created_at": row[11].isoformat() if row[11] is not None else None,
            }
        )
    return result
