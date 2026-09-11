from datetime import datetime, timedelta
from zoneinfo import ZoneInfo
from uuid import uuid5, NAMESPACE_URL

SEOUL = ZoneInfo("Asia/Seoul")


def retention_start(now: datetime) -> datetime:
    local = now.astimezone(SEOUL)
    try:
        return local.replace(year=local.year - 2)
    except ValueError:
        return local.replace(year=local.year - 2, day=28)


def minute(value: datetime) -> datetime:
    if value.tzinfo is None:
        raise ValueError("시간대가 있는 시각이 필요합니다.")
    return value.astimezone(SEOUL).replace(second=0, microsecond=0)


def next_window(cursor: datetime, end: datetime):
    # Inclusive API minute bounds: repeat the boundary minute; UPSERT deduplicates.
    return minute(cursor), min(minute(cursor) + timedelta(days=1), minute(end))


def canonical_order(value):
    text = str(value or "0").strip()
    return str(int(text)) if text.isdigit() else text.casefold()


def notice_id(number, order):
    return uuid5(NAMESPACE_URL, f"geoflow:g2b:service:{number}:{canonical_order(order)}")
