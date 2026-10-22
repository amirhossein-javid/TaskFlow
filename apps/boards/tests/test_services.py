from datetime import date
from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.boards.models import Task, TaskActivity, TaskComment
from apps.boards.services import (
    create_column,
    create_task,
    create_task_comment,
    delete_column,
    delete_task,
    delete_task_comment,
    move_task,
    nudge_task,
    rename_column,
    reorder_columns,
    shift_column,
    update_task,
    update_task_comment,
)
from apps.projects.models import Project
from apps.workspaces.models import WorkspaceMembership
from apps.workspaces.services import create_workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def board_context():
    owner = User.objects.create_user(email="owner@example.com", password="SecurePass123!")
    member = User.objects.create_user(email="member@example.com", password="SecurePass123!")
    outsider = User.objects.create_user(email="outsider@example.com", password="SecurePass123!")
    workspace = create_workspace(user=owner, name="Product", slug="product")
    owner_membership = workspace.memberships.get(user=owner)
    member_membership = WorkspaceMembership.objects.create(
        workspace=workspace,
        user=member,
        role=WorkspaceMembership.Role.MEMBER,
    )
    project = Project.objects.create(workspace=workspace, name="Launch", creator=owner)
    return {
        "owner": owner,
        "member": member,
        "outsider": outsider,
        "workspace": workspace,
        "owner_membership": owner_membership,
        "member_membership": member_membership,
        "project": project,
        "board": project.board,
    }


def test_manager_can_create_rename_and_reorder_columns(board_context):
    board = board_context["board"]
    actor = board_context["owner_membership"]
    column = create_column(board=board, actor=actor, name=" بررسی ")
    rename_column(column=column, actor=actor, name="آماده انتشار")
    ordered_ids = list(board.columns.values_list("id", flat=True))[::-1]

    reorder_columns(board=board, actor=actor, ordered_ids=ordered_ids)

    column.refresh_from_db()
    assert column.name == "آماده انتشار"
    assert list(board.columns.values_list("id", flat=True)) == ordered_ids
    assert list(board.columns.values_list("position", flat=True)) == list(range(4))


def test_member_cannot_manage_columns(board_context):
    with pytest.raises(PermissionDenied):
        create_column(
            board=board_context["board"],
            actor=board_context["member_membership"],
            name="Blocked",
        )


def test_column_with_tasks_cannot_be_deleted(board_context):
    column = board_context["board"].columns.first()
    create_task(
        column=column,
        actor=board_context["member_membership"],
        title="Task",
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )

    with pytest.raises(ValidationError) as exc_info:
        delete_column(column=column, actor=board_context["owner_membership"])
    assert "جابه‌جا" in exc_info.value.messages[0]


def test_empty_column_deletion_normalizes_positions(board_context):
    board = board_context["board"]
    column = board.columns.get(position=1)

    delete_column(column=column, actor=board_context["owner_membership"])

    assert list(board.columns.values_list("position", flat=True)) == [0, 1]


def test_member_can_create_and_update_task(board_context):
    column = board_context["board"].columns.first()
    task = create_task(
        column=column,
        actor=board_context["member_membership"],
        title=" First task ",
        description="Initial",
        priority=Task.Priority.LOW,
        due_date=None,
        assignee=board_context["member"],
    )

    updated = update_task(
        task=task,
        actor=board_context["member_membership"],
        title="Updated task",
        description="Done",
        priority=Task.Priority.HIGH,
        due_date=date(2027, 1, 15),
        assignee=None,
    )

    assert updated.title == "Updated task"
    assert updated.creator == board_context["member"]
    assert updated.priority == Task.Priority.HIGH
    assert updated.assignee is None

    assert list(task.activities.values_list("event_type", flat=True)) == [
        TaskActivity.EventType.ASSIGNEE_CHANGED,
        TaskActivity.EventType.TASK_UPDATED,
        TaskActivity.EventType.TASK_CREATED,
    ]


def test_task_activity_skips_no_op_updates_and_incidental_reordering(board_context):
    actor = board_context["member_membership"]
    column = board_context["board"].columns.first()
    first = create_task(
        column=column,
        actor=actor,
        title="First",
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )
    second = create_task(
        column=column,
        actor=actor,
        title="Second",
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )

    update_task(
        task=first,
        actor=actor,
        title=first.title,
        description=first.description,
        priority=first.priority,
        due_date=first.due_date,
        assignee=first.assignee,
    )
    move_task(task=second, actor=actor, target_column=column, target_position=0)

    assert list(first.activities.values_list("event_type", flat=True)) == [
        TaskActivity.EventType.TASK_CREATED
    ]
    assert list(second.activities.values_list("event_type", flat=True)) == [
        TaskActivity.EventType.TASK_MOVED,
        TaskActivity.EventType.TASK_CREATED,
    ]


def test_activity_failure_rolls_back_task_update(board_context):
    actor = board_context["member_membership"]
    task = create_task(
        column=board_context["board"].columns.first(),
        actor=actor,
        title="Original",
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )

    with (
        patch.object(TaskActivity.objects, "create", side_effect=RuntimeError("storage error")),
        pytest.raises(RuntimeError, match="storage error"),
    ):
        update_task(
            task=task,
            actor=actor,
            title="Changed",
            description="",
            priority=Task.Priority.MEDIUM,
            due_date=None,
            assignee=None,
        )

    task.refresh_from_db()
    assert task.title == "Original"


def test_task_deletion_preserves_activity_with_snapshot(board_context):
    task = create_task(
        column=board_context["board"].columns.first(),
        actor=board_context["member_membership"],
        title="Disposable",
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )

    delete_task(task=task, actor=board_context["member_membership"])

    events = TaskActivity.objects.filter(task_title="Disposable")
    assert list(events.values_list("event_type", flat=True)) == [
        TaskActivity.EventType.TASK_DELETED,
        TaskActivity.EventType.TASK_CREATED,
    ]
    assert all(event.task is None for event in events)


def test_comment_services_enforce_ownership_and_record_meaningful_activity(board_context):
    task = create_task(
        column=board_context["board"].columns.first(),
        actor=board_context["member_membership"],
        title="Discuss",
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )
    comment = create_task_comment(
        task=task,
        actor=board_context["member_membership"],
        body="  First comment  ",
    )

    with pytest.raises(PermissionDenied):
        update_task_comment(
            comment=comment,
            actor=board_context["owner_membership"],
            body="Owner edit",
        )
    update_task_comment(
        comment=comment,
        actor=board_context["member_membership"],
        body="First comment",
    )
    updated = update_task_comment(
        comment=comment,
        actor=board_context["member_membership"],
        body="Updated comment",
    )

    assert updated.body == "Updated comment"
    assert list(
        task.activities.filter(event_type__startswith="comment").values_list(
            "event_type", flat=True
        )
    ) == [
        TaskActivity.EventType.COMMENT_EDITED,
        TaskActivity.EventType.COMMENT_CREATED,
    ]

    delete_task_comment(comment=updated, actor=board_context["member_membership"])
    assert not TaskComment.objects.filter(pk=comment.pk).exists()
    assert task.activities.first().event_type == TaskActivity.EventType.COMMENT_DELETED


def test_archived_project_blocks_comment_mutations(board_context):
    task = create_task(
        column=board_context["board"].columns.first(),
        actor=board_context["member_membership"],
        title="Archived",
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )
    comment = create_task_comment(
        task=task,
        actor=board_context["member_membership"],
        body="Before archive",
    )
    board_context["project"].status = Project.Status.ARCHIVED
    board_context["project"].save(update_fields=["status"])

    with pytest.raises(ValidationError, match="فقط قابل مشاهده"):
        create_task_comment(
            task=task,
            actor=board_context["member_membership"],
            body="Blocked",
        )
    with pytest.raises(ValidationError, match="فقط قابل مشاهده"):
        update_task_comment(
            comment=comment,
            actor=board_context["member_membership"],
            body="Blocked",
        )
    with pytest.raises(ValidationError, match="فقط قابل مشاهده"):
        delete_task_comment(comment=comment, actor=board_context["member_membership"])


def test_task_rejects_assignee_outside_workspace(board_context):
    column = board_context["board"].columns.first()

    with pytest.raises(ValidationError, match="عضو همین فضای کاری"):
        create_task(
            column=column,
            actor=board_context["member_membership"],
            title="Task",
            description="",
            priority=Task.Priority.MEDIUM,
            due_date=None,
            assignee=board_context["outsider"],
        )


def test_move_task_between_columns_keeps_dense_deterministic_order(board_context):
    actor = board_context["member_membership"]
    source, target = board_context["board"].columns.all()[:2]
    first = create_task(
        column=source,
        actor=actor,
        title="First",
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )
    second = create_task(
        column=source,
        actor=actor,
        title="Second",
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )

    move_task(task=second, actor=actor, target_column=target, target_position=0)
    move_task(task=first, actor=actor, target_column=target, target_position=0)

    assert list(source.tasks.values_list("position", flat=True)) == []
    assert list(target.tasks.values_list("title", "position")) == [
        ("First", 0),
        ("Second", 1),
    ]


def test_move_task_within_column_respects_unique_positions(board_context):
    actor = board_context["member_membership"]
    column = board_context["board"].columns.first()
    tasks = [
        create_task(
            column=column,
            actor=actor,
            title=title,
            description="",
            priority=Task.Priority.MEDIUM,
            due_date=None,
            assignee=None,
        )
        for title in ["First", "Second", "Third"]
    ]

    move_task(task=tasks[2], actor=actor, target_column=column, target_position=0)
    move_task(task=tasks[0], actor=actor, target_column=column, target_position=2)

    assert list(column.tasks.values_list("title", "position")) == [
        ("Third", 0),
        ("Second", 1),
        ("First", 2),
    ]


def test_nudge_uses_fresh_task_position_after_prior_move(board_context):
    actor = board_context["member_membership"]
    column = board_context["board"].columns.first()
    first, second, _third = [
        create_task(
            column=column,
            actor=actor,
            title=title,
            description="",
            priority=Task.Priority.MEDIUM,
            due_date=None,
            assignee=None,
        )
        for title in ["First", "Second", "Third"]
    ]
    stale_second = Task.objects.select_related("column").get(pk=second.pk)
    move_task(task=second, actor=actor, target_column=column, target_position=0)

    nudge_task(task=stale_second, actor=actor, direction="down")

    assert list(column.tasks.values_list("title", "position")) == [
        (first.title, 0),
        (second.title, 1),
        ("Third", 2),
    ]


def test_shift_column_uses_fresh_order_after_prior_reorder(board_context):
    board = board_context["board"]
    actor = board_context["owner_membership"]
    original = list(board.columns.all())
    stale_middle = original[1]
    reorder_columns(
        board=board,
        actor=actor,
        ordered_ids=[column.pk for column in reversed(original)],
    )

    shift_column(column=stale_middle, actor=actor, direction="up")

    assert list(board.columns.values_list("id", flat=True)) == [
        stale_middle.pk,
        original[2].pk,
        original[0].pk,
    ]


def test_delete_task_normalizes_only_its_column(board_context):
    actor = board_context["member_membership"]
    first_column, second_column = board_context["board"].columns.all()[:2]
    first = create_task(
        column=first_column,
        actor=actor,
        title="First",
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )
    create_task(
        column=first_column,
        actor=actor,
        title="Second",
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )
    other = create_task(
        column=second_column,
        actor=actor,
        title="Other",
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )

    delete_task(task=first, actor=actor)

    other.refresh_from_db()
    assert list(first_column.tasks.values_list("position", flat=True)) == [0]
    assert other.position == 0


def test_archived_project_blocks_all_mutations(board_context):
    project = board_context["project"]
    project.status = Project.Status.ARCHIVED
    project.save(update_fields=["status"])

    with pytest.raises(ValidationError, match="فقط قابل مشاهده"):
        create_task(
            column=board_context["board"].columns.first(),
            actor=board_context["member_membership"],
            title="Blocked",
            description="",
            priority=Task.Priority.MEDIUM,
            due_date=None,
            assignee=None,
        )
