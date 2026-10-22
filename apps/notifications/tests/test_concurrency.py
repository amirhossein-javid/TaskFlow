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


def test_concurrent_read_requests_preserve_first_read_time(context, assigned_task):
    from apps.notifications.services import set_notification_read

    note = Notification.objects.get()
    user = context["member"].user
    run_concurrently(
        *[
            lambda: set_notification_read(user=user, notification_id=note.pk, read=True)
            for _ in range(2)
        ]
    )
    note.refresh_from_db()
    first_read = note.read_at
    assert first_read is not None
    assert set_notification_read(user=user, notification_id=note.pk, read=True) == 0
    note.refresh_from_db()
    assert note.read_at == first_read


def test_membership_removal_and_comment_creation_do_not_deadlock(context, assigned_task):
    from apps.workspaces.services import remove_membership

    run_concurrently(
        lambda: remove_membership(actor=context["actor"], target=context["member"]),
        lambda: create_task_comment(task=assigned_task, actor=context["actor"], body="Concurrent"),
    )
    assert assigned_task.comments.count() == 1
    assert not Notification.objects.visible_to(context["member"].user).exists()


def test_read_all_uses_statement_snapshot_and_leaves_later_notification_unread(
    context, assigned_task
):
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue
    from threading import Event
    from time import monotonic

    from django.db import close_old_connections, connection, transaction

    from apps.notifications.services import mark_all_notifications_read

    backend_ids = Queue()
    note = Notification.objects.get()

    def mark_all():
        close_old_connections()
        try:
            connection.ensure_connection()
            backend_ids.put(connection.connection.info.backend_pid)
            return mark_all_notifications_read(user=context["member"].user)
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            Notification.objects.select_for_update().get(pk=note.pk)
            future = executor.submit(mark_all)
            backend_id = backend_ids.get(timeout=5)
            deadline = monotonic() + 5
            while True:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_stat_clear_snapshot()")
                    cursor.execute(
                        "SELECT wait_event_type FROM pg_stat_activity WHERE pid = %s", [backend_id]
                    )
                    waiting = cursor.fetchone()[0] == "Lock"
                if waiting:
                    break
                assert monotonic() < deadline, "Read-all did not reach the row lock"
                Event().wait(0.01)
            create_task_comment(task=assigned_task, actor=context["actor"], body="After snapshot")
        assert future.result(timeout=10) == 1
    note.refresh_from_db()
    assert note.read_at is not None
    later = Notification.objects.get(kind=Notification.Kind.COMMENT)
    assert later.read_at is None


def test_simultaneous_assignment_of_same_user_notifies_once(context, assigned_task):
    from .test_triggers import edit

    edit(assigned_task, context["actor"], None)
    Notification.objects.all().delete()
    run_concurrently(
        *[lambda: edit(assigned_task, context["actor"], context["member"].user) for _ in range(2)]
    )
    assert Notification.objects.count() == 1
    assert Notification.objects.get().kind == Notification.Kind.ASSIGNMENT


def test_comment_and_reassignment_use_serialized_current_assignee(context, assigned_task):
    from .test_triggers import edit

    run_concurrently(
        lambda: edit(assigned_task, context["actor"], context["actor"].user),
        lambda: create_task_comment(task=assigned_task, actor=context["actor"], body="Concurrent"),
    )
    reassignment = assigned_task.activities.get(event_type="assignee_changed")
    comment = assigned_task.activities.get(event_type="comment_created")
    notes = Notification.objects.filter(kind=Notification.Kind.COMMENT)
    if comment.pk < reassignment.pk:
        assert notes.get().recipient_id == context["member"].user_id
    else:
        assert not notes.exists()


@pytest.mark.parametrize("operation", ["read", "read_all"])
def test_read_requests_waiting_on_same_row_update_only_once(context, assigned_task, operation):
    from concurrent.futures import ThreadPoolExecutor
    from queue import Queue
    from threading import Event
    from time import monotonic

    from django.db import close_old_connections, connection, transaction

    from apps.notifications.services import set_notification_read

    note = Notification.objects.get()
    backend_ids = Queue()

    def read():
        from apps.notifications.services import mark_all_notifications_read

        close_old_connections()
        try:
            connection.ensure_connection()
            backend_ids.put(connection.connection.info.backend_pid)
            if operation == "read_all":
                return mark_all_notifications_read(user=context["member"].user)
            return set_notification_read(
                user=context["member"].user, notification_id=note.pk, read=True
            )
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        with transaction.atomic():
            Notification.objects.select_for_update().get(pk=note.pk)
            futures = [executor.submit(read) for _ in range(2)]
            pids = [backend_ids.get(timeout=5) for _ in range(2)]
            deadline = monotonic() + 5
            while True:
                with connection.cursor() as cursor:
                    cursor.execute("SELECT pg_stat_clear_snapshot()")
                    cursor.execute(
                        "SELECT count(*) FROM pg_stat_activity WHERE pid = ANY(%s) AND wait_event_type = 'Lock'",
                        [pids],
                    )
                    if cursor.fetchone()[0] == 2:
                        break
                assert monotonic() < deadline, "Read requests did not reach their row locks"
                Event().wait(0.01)
        assert sorted(future.result(timeout=10) for future in futures) == [0, 1]


def test_cross_project_reciprocal_comments_do_not_deadlock(context, assigned_task):
    from threading import Barrier

    from django.db import connection, transaction

    from apps.boards.services import create_task
    from apps.projects.models import Project

    second_project = Project.objects.create(
        workspace=context["board"].project.workspace,
        creator=context["actor"].user,
        name="Second project",
    )
    second_task = create_task(
        column=second_project.board.columns.first(),
        actor=context["member"],
        title="Reciprocal task",
        description="",
        priority=assigned_task.priority,
        due_date=None,
        assignee=context["actor"].user,
    )
    ready_to_commit = Barrier(2)

    def comment(task, actor):
        # Keep both service transactions open until both actors have acquired
        # their locks and inserted notifications. Deferred recipient FK checks
        # then run concurrently at commit, exposing accidental User row locks.
        with transaction.atomic():
            with connection.cursor() as cursor:
                cursor.execute("SET LOCAL lock_timeout = '5s'")
                cursor.execute("SET LOCAL statement_timeout = '10s'")
            create_task_comment(task=task, actor=actor, body="Reciprocal comment")
            ready_to_commit.wait(timeout=5)

    # The shared runner starts each action on an independent connection and
    # bounds both the initial barrier and future completion.
    run_concurrently(
        lambda: comment(assigned_task, context["actor"]),
        lambda: comment(second_task, context["member"]),
    )
    notes = list(
        Notification.objects.filter(kind=Notification.Kind.COMMENT).select_related("activity")
    )
    assert len(notes) == 2
    assert {(note.task_id, note.activity.actor_id, note.recipient_id) for note in notes} == {
        (assigned_task.pk, context["actor"].user_id, context["member"].user_id),
        (second_task.pk, context["member"].user_id, context["actor"].user_id),
    }
    for task, project in [(assigned_task, context["board"].project), (second_task, second_project)]:
        saved_comment = task.comments.get()
        note = next(note for note in notes if note.task_id == task.pk)
        assert note.activity.task_id == task.pk
        assert note.activity.project_id == project.pk
        assert note.activity.event_type == "comment_created"
        assert note.activity.metadata == {"comment_id": saved_comment.pk}
        task.refresh_from_db()
        assert task.position == 0
