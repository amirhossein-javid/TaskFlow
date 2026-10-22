from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.boards.models import Task, TaskActivity, TaskComment
from apps.boards.services import (
    create_task,
    create_task_comment,
    delete_task,
    move_task,
    nudge_task,
    update_task,
    update_task_comment,
)
from apps.notifications.models import Notification
from apps.notifications.services import notify_task_assignee
from apps.projects.services import set_project_archived

pytestmark = pytest.mark.django_db


def edit(task, actor, assignee):
    return update_task(
        task=task,
        actor=actor,
        title=task.title,
        description=task.description,
        priority=task.priority,
        due_date=task.due_date,
        assignee=assignee,
    )


def test_assignment_uses_existing_activity_and_skips_noops(context, assigned_task):
    task = assigned_task
    note = Notification.objects.get()
    assert note.recipient_id == context["member"].user_id
    assert note.kind == Notification.Kind.ASSIGNMENT
    assert note.activity.event_type == TaskActivity.EventType.TASK_CREATED
    assert str(note) == note.get_kind_display()
    edit(task, context["actor"], task.assignee)
    assert Notification.objects.count() == 1
    edit(task, context["actor"], None)
    assert Notification.objects.count() == 1
    edit(task, context["actor"], context["member"].user)
    assert Notification.objects.count() == 2
    note = Notification.objects.first()
    assert note.activity.event_type == TaskActivity.EventType.ASSIGNEE_CHANGED
    notify_task_assignee(task=task, activity=note.activity, kind=Notification.Kind.ASSIGNMENT)
    assert Notification.objects.count() == 2
    with transaction.atomic(), pytest.raises(IntegrityError):
        Notification.objects.create(
            task=task, activity=note.activity, recipient=note.recipient, kind=note.kind
        )


def test_comment_only_notifies_current_assignee(context, assigned_task):
    task = assigned_task
    comment = create_task_comment(task=task, actor=context["actor"], body="Comment")
    note = Notification.objects.get(kind=Notification.Kind.COMMENT)
    assert note.recipient_id == context["member"].user_id
    assert note.activity.metadata == {"comment_id": comment.pk}
    update_task_comment(comment=comment, actor=context["actor"], body="Edited")
    create_task_comment(task=task, actor=context["member"], body="Self")
    assert Notification.objects.filter(kind=Notification.Kind.COMMENT).count() == 1
    edit(task, context["actor"], None)
    create_task_comment(task=task, actor=context["actor"], body="Unassigned")
    assert Notification.objects.filter(kind=Notification.Kind.COMMENT).count() == 1


@pytest.mark.parametrize("nudge", [False, True])
def test_column_changes_only_notify_on_real_transition(context, assigned_task, nudge):
    task = assigned_task
    if nudge:
        nudge_task(task=task, actor=context["actor"], direction="next")
    else:
        target = context["board"].columns.all()[1]
        move_task(task=task, actor=context["actor"], target_column=target, target_position=0)
        move_task(task=task, actor=context["actor"], target_column=target, target_position=0)
    note = Notification.objects.get(kind=Notification.Kind.COLUMN_CHANGE)
    assert note.activity.metadata["from_column_id"] != note.activity.metadata["to_column_id"]
    task.refresh_from_db()
    create_task(
        column=task.column,
        actor=context["actor"],
        title="Other",
        description="",
        priority=Task.Priority.LOW,
        assignee=None,
        due_date=None,
    )
    nudge_task(task=task, actor=context["actor"], direction="down")
    assert Notification.objects.filter(kind=Notification.Kind.COLUMN_CHANGE).count() == 1
    assert task.activities.filter(event_type="task_moved").count() == 2


@pytest.mark.parametrize("invalid", ["self", "inactive", "removed"])
def test_invalid_recipients_are_not_notified(context, assigned_task, invalid):
    member = context["member"]
    if invalid == "self":
        actor = member
    else:
        actor = context["actor"]
        if invalid == "removed":
            member.delete()
        else:
            member.user.is_active = False
            member.user.save(update_fields=["is_active"])
    create_task_comment(task=assigned_task, actor=actor, body="No notification")
    assert Notification.objects.filter(kind=Notification.Kind.COMMENT).count() == 0


@pytest.mark.parametrize("operation", ["create", "assign", "comment", "move", "nudge"])
def test_notification_failure_rolls_back_domain_and_history(context, assigned_task, operation):
    task = assigned_task
    if operation == "assign":
        edit(task, context["actor"], None)
    before_events = TaskActivity.objects.count()
    before_tasks = Task.objects.count()
    with patch.object(Notification.objects, "get_or_create", side_effect=RuntimeError("failed")):
        with pytest.raises(RuntimeError, match="failed"):
            if operation == "create":
                create_task(
                    column=task.column,
                    actor=context["actor"],
                    title="Rollback",
                    description="",
                    priority=task.priority,
                    due_date=None,
                    assignee=context["member"].user,
                )
            elif operation == "assign":
                edit(task, context["actor"], context["member"].user)
            elif operation == "comment":
                create_task_comment(task=task, actor=context["actor"], body="Rollback")
            elif operation == "move":
                move_task(
                    task=task,
                    actor=context["actor"],
                    target_column=context["board"].columns.all()[1],
                    target_position=0,
                )
            else:
                nudge_task(task=task, actor=context["actor"], direction="next")
    task.refresh_from_db()
    assert task.column_id == context["board"].columns.first().pk
    assert task.position == 0
    if operation == "assign":
        assert task.assignee_id is None
    assert TaskActivity.objects.count() == before_events
    assert Task.objects.count() == before_tasks
    assert not TaskComment.objects.exists()
    assert Notification.objects.count() == 1


def test_archive_and_deletion_preserve_existing_contracts(context, assigned_task):
    task = assigned_task
    set_project_archived(project=context["board"].project, actor=context["actor"], archived=True)
    with pytest.raises(ValidationError):
        create_task_comment(task=task, actor=context["actor"], body="Blocked")
    assert Notification.objects.count() == 1
    set_project_archived(project=context["board"].project, actor=context["actor"], archived=False)
    event_id = Notification.objects.get().activity_id
    delete_task(task=task, actor=context["actor"])
    assert not Notification.objects.exists()
    assert TaskActivity.objects.get(pk=event_id).task_id is None


def test_invalid_kind_is_rejected_by_database(context, assigned_task):
    note = Notification.objects.get()
    with transaction.atomic(), pytest.raises(IntegrityError):
        Notification.objects.filter(pk=note.pk).update(kind="invalid")


def test_notification_admin_is_read_only(client, context, assigned_task):
    from django.urls import reverse

    admin = context["actor"].user
    admin.is_staff = admin.is_superuser = True
    admin.save(update_fields=["is_staff", "is_superuser"])
    client.force_login(admin)
    note = Notification.objects.get()
    assert (
        client.get(reverse("admin:notifications_notification_change", args=[note.pk])).status_code
        == 200
    )
    assert client.get(reverse("admin:notifications_notification_add")).status_code == 403
    assert (
        client.post(
            reverse("admin:notifications_notification_change", args=[note.pk]), {"kind": "comment"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            reverse("admin:notifications_notification_delete", args=[note.pk]), {"post": "yes"}
        ).status_code
        == 403
    )
    note.refresh_from_db()
    assert note.kind == Notification.Kind.ASSIGNMENT
