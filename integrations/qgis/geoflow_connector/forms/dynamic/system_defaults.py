"""System-owned defaults applied only to a newly-created GIS feature."""
from __future__ import annotations

import datetime as dt


WORK_DATE_NAMES = {"work_date", "workdate", "wrk_date", "survey_date", "작업일"}


def field_names(field):
    storage = field.get("storage") if isinstance(field.get("storage"), dict) else {}
    return {
        str(field.get(key) or "").strip().casefold()
        for key in ("id", "name", "field_name", "field_identifier", "label")
    } | {str(storage.get("key") or "").strip().casefold()}


def _empty_work_date(value):
    if value in (None, ""):
        return True
    if isinstance(value, (dt.datetime, dt.date)):
        year = value.year
    else:
        text = str(value or "").strip()
        year = int(text[:4]) if len(text) >= 4 and text[:4].isdigit() else 9999
    return year <= 2000


def new_feature_defaults(fields, values, user_context, *, today=None):
    defaults = {}
    today = today or dt.date.today()
    linked_worker = (
        str((user_context or {}).get("worker_id") or "")
        if (user_context or {}).get("worker_link_status") == "linked" else ""
    )
    for field in fields:
        field_id = field["id"]
        names = field_names(field)
        current = values.get(field_id)
        kind = str(field.get("semantic_data_type") or field.get("widget_type") or "").casefold()
        if kind == "date" and names & WORK_DATE_NAMES and _empty_work_date(current):
            defaults[field_id] = today.isoformat()
        if linked_worker and "worker_id" in names and current in (None, ""):
            defaults[field_id] = linked_worker
    return defaults
