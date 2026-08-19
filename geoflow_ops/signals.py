from __future__ import annotations

from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from geoflow_ops.models import ProcessEvent
from geoflow_ops.services.workflow_state import (
    event_affects_contract_lifecycle,
    sync_contract_status_from_events,
)


@receiver(pre_save, sender=ProcessEvent)
def remember_previous_event_lifecycle(sender, instance, using, **kwargs):
    """Remember the old milestone fields so edits/voids can trigger recompute."""
    previous = None
    if getattr(instance, "pk", None):
        previous = (
            sender.objects.using(using)
            .filter(pk=instance.pk)
            .values("contract_id", "stage", "event_type", "status")
            .first()
        )
    instance._gf_previous_lifecycle_event = previous


@receiver(post_save, sender=ProcessEvent)
def sync_contract_lifecycle_after_event_save(sender, instance, using, **kwargs):
    previous = getattr(instance, "_gf_previous_lifecycle_event", None) or {}
    previous_affects = event_affects_contract_lifecycle(
        previous.get("stage"), previous.get("event_type")
    )
    current_affects = event_affects_contract_lifecycle(
        getattr(instance, "stage", None), getattr(instance, "event_type", None)
    )

    if not previous_affects and not current_affects:
        return

    contract_ids = {
        str(value)
        for value in (
            previous.get("contract_id"),
            getattr(instance, "contract_id", None),
        )
        if value
    }
    for contract_id in contract_ids:
        sync_contract_status_from_events(using, contract_id)
