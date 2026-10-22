from django.utils import timezone

from apps.accounts.models import User

from .models import Notification


def notify_task_assignee(*, task, activity, kind):
    """Called only inside the owning task service's existing transaction."""
    recipient_id = task.assignee_id
    if recipient_id is None or recipient_id == activity.actor_id:
        return
    # Match TaskDetailView access: current membership in the task's workspace.
    # Do not lock another membership after the task: owner-safety services lock
    # all memberships in primary-key order, so that would invert lock ordering.
    if not User.objects.filter(
        pk=recipient_id,
        is_active=True,
        workspace_memberships__workspace_id=activity.project.workspace_id,
    ).exists():
        return
    Notification.objects.get_or_create(
        recipient_id=recipient_id,
        activity=activity,
        defaults={"task": task, "kind": kind},
    )


def set_notification_read(*, user, notification_id, read):
    notifications = Notification.objects.visible_to(user).filter(pk=notification_id)
    if not notifications.exists():
        raise Notification.DoesNotExist
    # Keep the state predicate on the UPDATE target, outside the access subquery.
    # PostgreSQL then rechecks it after waiting for a concurrent row update.
    writable = Notification.objects.filter(pk__in=notifications.values("pk"))
    if read:
        return writable.filter(read_at__isnull=True).update(read_at=timezone.now())
    return writable.filter(read_at__isnull=False).update(read_at=None)


def mark_all_notifications_read(*, user):
    # One UPDATE: notifications committed after its statement snapshot stay unread.
    return Notification.objects.filter(
        pk__in=Notification.objects.visible_to(user).values("pk"), read_at__isnull=True
    ).update(read_at=timezone.now())
