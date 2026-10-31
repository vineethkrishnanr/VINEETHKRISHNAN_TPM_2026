from django.db.models.signals import post_save, pre_save
from django.dispatch import receiver

from .models import Task
from .notifications import send_assignment_notification


@receiver(pre_save, sender=Task)
def remember_previous_assignee(sender, instance, **kwargs):
    """Stash the assignee currently stored in the DB so post_save can compare."""
    if instance.pk is None:
        instance._previous_assignee_id = None
        return
    update_fields = kwargs.get("update_fields")
    if update_fields is not None and not {"assignee", "assignee_id"} & set(update_fields):
        instance._previous_assignee_id = instance.assignee_id
        return
    instance._previous_assignee_id = (
        Task.all_objects.filter(pk=instance.pk).values_list("assignee_id", flat=True).first()
    )


@receiver(post_save, sender=Task)
def notify_on_assignment(sender, instance, created, **kwargs):
    previous = getattr(instance, "_previous_assignee_id", None)
    if instance.assignee_id and instance.assignee_id != previous:
        send_assignment_notification(instance)
