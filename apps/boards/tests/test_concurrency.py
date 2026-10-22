from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection

from apps.accounts.models import User
from apps.boards.models import Task, TaskActivity, TaskComment
from apps.boards.services import (
    create_task,
    create_task_comment,
    delete_task_comment,
    move_task,
    nudge_task,
    reorder_columns,
    shift_column,
    update_task_comment,
)
from apps.projects.models import Project
from apps.workspaces.models import WorkspaceMembership
from apps.workspaces.services import create_workspace

pytestmark = pytest.mark.django_db(transaction=True)


def run_concurrently(*actions):
    barrier = Barrier(len(actions))

    def run(action):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            action()
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=len(actions)) as executor:
        futures = [executor.submit(run, action) for action in actions]
        for future in futures:
            future.result(timeout=15)


def make_board_context():
    owner = User.objects.create_user(email="owner@example.com", password="SecurePass123!")
    member = User.objects.create_user(email="member@example.com", password="SecurePass123!")
    workspace = create_workspace(user=owner, name="Concurrent", slug="concurrent-board")
    owner_membership = workspace.memberships.get(user=owner)
    member_membership = WorkspaceMembership.objects.create(
        workspace=workspace,
        user=member,
        role=WorkspaceMembership.Role.MEMBER,
    )
    project = Project.objects.create(workspace=workspace, name="Launch", creator=owner)
    return project.board, owner_membership, member_membership


def make_task(*, column, actor, title):
    return create_task(
        column=column,
        actor=actor,
        title=title,
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )


def test_concurrent_task_creation_allocates_unique_dense_positions():
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency is PostgreSQL-specific.")
    owner = User.objects.create_user(email="owner@example.com", password="SecurePass123!")
    member = User.objects.create_user(email="member@example.com", password="SecurePass123!")
    workspace = create_workspace(user=owner, name="Concurrent", slug="concurrent-board")
    membership = WorkspaceMembership.objects.create(
        workspace=workspace,
        user=member,
        role=WorkspaceMembership.Role.MEMBER,
    )
    project = Project.objects.create(workspace=workspace, name="Launch", creator=owner)
    column = project.board.columns.first()
    barrier = Barrier(2)

    def create(title):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            task = create_task(
                column=column,
                actor=membership,
                title=title,
                description="",
                priority=Task.Priority.MEDIUM,
                due_date=None,
                assignee=None,
            )
            return task.pk
        finally:
            connection.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        created_ids = list(executor.map(create, ["First", "Second"]))

    assert len(set(created_ids)) == 2
    assert list(column.tasks.values_list("position", flat=True)) == [0, 1]


def test_concurrent_moves_to_same_column_preserve_all_tasks_and_dense_positions():
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency is PostgreSQL-specific.")
    board, _owner, member = make_board_context()
    source, target = board.columns.all()[:2]
    first = make_task(column=source, actor=member, title="First")
    second = make_task(column=source, actor=member, title="Second")
    anchor = make_task(column=target, actor=member, title="Anchor")

    def move(task_id):
        task = Task.objects.select_related("column").get(pk=task_id)
        target_column = board.columns.get(pk=target.pk)
        move_task(
            task=task,
            actor=member,
            target_column=target_column,
            target_position=0,
        )

    run_concurrently(lambda: move(first.pk), lambda: move(second.pk))

    assert not source.tasks.exists()
    assert set(target.tasks.values_list("id", flat=True)) == {
        first.pk,
        second.pk,
        anchor.pk,
    }
    assert list(target.tasks.values_list("position", flat=True)) == [0, 1, 2]


def test_concurrent_opposite_nudges_use_fresh_locked_position():
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency is PostgreSQL-specific.")
    board, _owner, member = make_board_context()
    column = board.columns.first()
    first = make_task(column=column, actor=member, title="First")
    middle = make_task(column=column, actor=member, title="Middle")
    third = make_task(column=column, actor=member, title="Third")

    def nudge(direction):
        task = Task.objects.select_related("column").get(pk=middle.pk)
        nudge_task(task=task, actor=member, direction=direction)

    run_concurrently(lambda: nudge("up"), lambda: nudge("down"))

    assert list(column.tasks.values_list("id", "position")) == [
        (first.pk, 0),
        (middle.pk, 1),
        (third.pk, 2),
    ]


def test_concurrent_opposite_column_shifts_use_fresh_locked_order():
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency is PostgreSQL-specific.")
    board, owner, _member = make_board_context()
    columns = list(board.columns.all())
    middle = columns[1]

    def shift(direction):
        column = board.columns.get(pk=middle.pk)
        shift_column(column=column, actor=owner, direction=direction)

    run_concurrently(lambda: shift("up"), lambda: shift("down"))

    assert list(board.columns.values_list("id", "position")) == [
        (columns[0].pk, 0),
        (middle.pk, 1),
        (columns[2].pk, 2),
    ]


def test_concurrent_column_reorders_do_not_deadlock_or_break_unique_positions():
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency is PostgreSQL-specific.")
    board, owner, _member = make_board_context()
    ids = list(board.columns.values_list("id", flat=True))
    first_order = [ids[1], ids[2], ids[0]]
    second_order = [ids[2], ids[0], ids[1]]

    run_concurrently(
        lambda: reorder_columns(board=board, actor=owner, ordered_ids=first_order),
        lambda: reorder_columns(board=board, actor=owner, ordered_ids=second_order),
    )

    final_order = list(board.columns.values_list("id", flat=True))
    assert final_order in [first_order, second_order]
    assert list(board.columns.values_list("position", flat=True)) == [0, 1, 2]


def test_concurrent_task_move_and_column_reorder_complete_without_deadlock():
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency is PostgreSQL-specific.")
    board, owner, member = make_board_context()
    columns = list(board.columns.all())
    task = make_task(column=columns[0], actor=member, title="Moving task")
    reordered_ids = [columns[2].pk, columns[0].pk, columns[1].pk]

    def move():
        fresh_task = Task.objects.select_related("column").get(pk=task.pk)
        target = board.columns.get(pk=columns[1].pk)
        move_task(
            task=fresh_task,
            actor=member,
            target_column=target,
            target_position=0,
        )

    run_concurrently(
        move,
        lambda: reorder_columns(board=board, actor=owner, ordered_ids=reordered_ids),
    )

    task.refresh_from_db()
    assert task.column_id == columns[1].pk
    assert task.position == 0
    assert list(board.columns.values_list("id", flat=True)) == reordered_ids


def test_concurrent_comment_creation_records_each_comment_once():
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency is PostgreSQL-specific.")
    board, _owner, member = make_board_context()
    task = make_task(column=board.columns.first(), actor=member, title="Discuss")

    def create(body):
        fresh_task = Task.objects.select_related("column").get(pk=task.pk)
        create_task_comment(task=fresh_task, actor=member, body=body)

    run_concurrently(lambda: create("First"), lambda: create("Second"))

    assert set(task.comments.values_list("body", flat=True)) == {"First", "Second"}
    assert task.activities.filter(event_type=TaskActivity.EventType.COMMENT_CREATED).count() == 2


def test_concurrent_comment_edit_and_delete_finish_without_deadlock_or_resurrection():
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency is PostgreSQL-specific.")
    board, _owner, member = make_board_context()
    task = make_task(column=board.columns.first(), actor=member, title="Discuss")
    comment = create_task_comment(task=task, actor=member, body="Original")
    edit_comment = TaskComment.objects.select_related("task__column").get(pk=comment.pk)
    delete_comment = TaskComment.objects.select_related("task__column").get(pk=comment.pk)

    def edit():
        try:
            update_task_comment(comment=edit_comment, actor=member, body="Edited")
        except ValidationError:
            pass

    def delete():
        delete_task_comment(comment=delete_comment, actor=member)

    run_concurrently(edit, delete)

    assert not TaskComment.objects.filter(pk=comment.pk).exists()
    events = task.activities.filter(
        event_type__in=[
            TaskActivity.EventType.COMMENT_EDITED,
            TaskActivity.EventType.COMMENT_DELETED,
        ]
    )
    assert events.filter(event_type=TaskActivity.EventType.COMMENT_DELETED).count() == 1
    assert events.filter(event_type=TaskActivity.EventType.COMMENT_EDITED).count() <= 1
