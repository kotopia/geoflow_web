"""Project performance status: tenant settings/legacy project values, never events."""
from geoflow_ops.models import Project
from .tenant_settings import settings_options

# Existing codes/labels from gf-list-core; retain legacy spelling in storage.
LEGACY_LABELS = {"planned": "계약전", "active": "진행", "pause": "중지", "complete": "완료", "cancel": "취소", "canceld": "취소"}


def project_status_options(alias):
    options = dict(settings_options(alias, "project.status"))
    if not options:
        options.update(LEGACY_LABELS)
    for value in Project.objects.using(alias).exclude(status__isnull=True).values_list("status", flat=True).distinct():
        if value:
            options.setdefault(value, LEGACY_LABELS.get(value, value))
    return list(options.items())


def status_key(value):
    return "cancel" if value == "canceld" else (value or "")
