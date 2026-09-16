"""Historical scope selection; unset scope defaults to the recent calendar month."""
import calendar
from datetime import datetime, time, timedelta
from django.utils import timezone
from .models import CollectionPeriod
from .policy import SEOUL, minute, retention_start


def months_before(day, months):
    absolute = day.year * 12 + day.month - 1 - months
    year, month = divmod(absolute, 12)
    return day.replace(year=year, month=month + 1, day=min(day.day, calendar.monthrange(year, month + 1)[1]))


def selection(now=None):
    from .service import central_alias
    now = minute(now or timezone.now())
    saved = CollectionPeriod.objects.using(central_alias()).filter(pk=1).values_list("start_date", "end_date").first()
    start, end = saved or (months_before(now.date(), 1), now.date())
    return dict(start_date=start, end_date=end, default=saved is None,
                minimum_date=retention_start(now).date(), maximum_date=now.date(),
                signature=saved,
                start=max(datetime.combine(start, time.min, SEOUL), retention_start(now)),
                end=min(datetime.combine(end, time(23, 59), SEOUL), now))


def bounds(job, now):
    scope = selection(now)
    return max(scope["start"], job.backfill_start or retention_start(job.backfill_end)), min(scope["end"], job.backfill_end)


def select_checkpoint(previous, lower, upper):
    """Suspend out-of-scope page caches without discarding them; restore on expansion."""
    from django.utils.dateparse import parse_datetime
    waiting = list(previous.get("suspended_windows", []))
    active = {k: v for k, v in previous.items() if k != "suspended_windows"}
    if active.get("checkpoint_version") == 1 and not active.get("finished"):
        waiting.insert(0, active)
    for index, checkpoint in enumerate(waiting):
        if lower <= parse_datetime(checkpoint["start"]) < parse_datetime(checkpoint["end"]) <= upper:
            return waiting.pop(index), waiting
    return {}, waiting
