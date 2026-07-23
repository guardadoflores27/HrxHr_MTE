# planning/signals.py
# ─────────────────────────────────────────────────────────────────────────────
# Keeps production Operational Events in sync with planning Time Blocks.
#
# Whenever a HourlyPlanBlock is created or updated, we (re)generate its single
# ExecutionEvent; when it is deleted, we remove that event. All real logic
# lives in production.block_bridge — these handlers are deliberately thin.
# ─────────────────────────────────────────────────────────────────────────────

from django.db.models.signals import post_save, post_delete, pre_delete
from django.dispatch import receiver

from .models import HourlyPlan, HourlyPlanBlock


@receiver(post_save, sender=HourlyPlanBlock, dispatch_uid="block_to_event_save")
def block_saved(sender, instance, **kwargs):
    # Imported lazily to avoid app-loading import cycles.
    from production.block_bridge import sync_event_for_block
    sync_event_for_block(instance)


@receiver(pre_delete, sender=HourlyPlanBlock, dispatch_uid="block_to_event_delete")
def block_deleted(sender, instance, **kwargs):
    from production.block_bridge import remove_event_for_block
    remove_event_for_block(instance.pk)


@receiver(post_save, sender=HourlyPlan, dispatch_uid="hour_adopts_orphan_blocks")
def hour_created(sender, instance, created, **kwargs):
    """Adopt Time Blocks that were dropped on this hour BEFORE it existed.

    Blocks can be placed on a pending overtime slot before its model is saved.
    At that moment there is no HourlyPlan for the slot, so block_bridge cannot
    attach an ExecutionEvent and the block stays orphaned — invisible to the
    dashboard. As soon as the hour is created we re-sync every block sitting on
    that same slot, which finally generates their events.
    """
    if not created:
        return
    from production.block_bridge import sync_event_for_block

    orphans = HourlyPlanBlock.objects.filter(
        daily_plan_id=instance.daily_plan_id,
        slot_time=instance.hour,
    )
    for block in orphans:
        sync_event_for_block(block)