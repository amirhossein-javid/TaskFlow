from datetime import date

import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.boards.models import Task
from apps.boards.services import (
    create_column,
    create_task,
    delete_column,
    delete_task,
    move_task,
    rename_column,
    reorder_columns,
    update_task,
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
