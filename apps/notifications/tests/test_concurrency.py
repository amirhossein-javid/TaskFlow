import pytest

from apps.boards.services import create_task_comment, move_task
from apps.boards.tests.test_concurrency import run_concurrently
from apps.notifications.models import Notification

pytestmark = pytest.mark.django_db(transaction=True)


def test_simultaneous_same_column_move_notifies_once(context, assigned_task):
    target = context["board"].columns.all()[1]
    run_concurrently(
        *[
            lambda: move_task(
                task=assigned_task, actor=context["actor"], target_column=target, target_position=0
            )
            for _ in range(2)
        ]
    )
    assert Notification.objects.filter(kind=Notification.Kind.COLUMN_CHANGE).count() == 1
    assigned_task.refresh_from_db()
    assert assigned_task.column_id == target.pk
    assert assigned_task.position == 0


def test_concurrent_comments_each_notify_once(context, assigned_task):
    run_concurrently(
        *[
            lambda: create_task_comment(task=assigned_task, actor=context["actor"], body="Comment")
            for _ in range(2)
        ]
    )
    assert Notification.objects.filter(kind=Notification.Kind.COMMENT).count() == 2
    assert assigned_task.comments.count() == 2
