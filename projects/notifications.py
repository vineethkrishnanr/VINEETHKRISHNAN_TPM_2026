import logging

from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger(__name__)


def send_assignment_notification(task):
    """Notification stub: logs the event and sends an email.

    With the default console email backend the email is printed in the terminal.
    Replace the body with a real provider / push / websocket later.
    """
    assignee = task.assignee
    if assignee is None:
        return
    logger.info("Task #%s '%s' assigned to %s", task.pk, task.title, assignee.username)
    if assignee.email:
        send_mail(
            subject=f"[{task.project.name}] You were assigned: {task.title}",
            message=(
                f"Hi {assignee.get_username()},\n\n"
                f"You have been assigned the task '{task.title}' "
                f"(priority: {task.priority}, due: {task.due_date or 'not set'}).\n"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[assignee.email],
            fail_silently=True,
        )
