from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, transaction

from apps.accounts.models import User
from apps.boards.models import Task
from apps.boards.services import create_task, update_task
from apps.projects.models import Project
from apps.workspaces.models import Workspace
from apps.workspaces.services import (
    accept_invitation,
    change_membership_role,
    create_invitation,
    create_workspace,
    delete_workspace,
    update_workspace,
)

pytestmark = pytest.mark.django_db(transaction=True)


def worker(action):
    close_old_connections()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '5s'")
            cursor.execute("SET statement_timeout = '10s'")
        return action()
    finally:
        connection.close()


@pytest.mark.parametrize("operation", ["update", "delete"])
def test_concurrency_workspace_write_rechecks_role_after_lock_wait(operation):
    owner = User.objects.create_user("owner@example.com")
    second = User.objects.create_user("second@example.com")
    workspace = create_workspace(user=owner, name="Original", slug="original")
    actor = workspace.memberships.get(user=owner)
    other = workspace.memberships.create(user=second, role="owner")
    barrier = Barrier(2)

    def write():
        barrier.wait(timeout=5)
        try:
            if operation == "update":
                update_workspace(workspace=workspace, actor=actor, name="Changed", slug="changed")
            else:
                delete_workspace(workspace=workspace, actor=actor, confirmation="Original")
        except PermissionDenied:
            return "forbidden"
        return "written"

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            change_membership_role(actor=other, target=actor, role="member")
            future = executor.submit(worker, write)
            barrier.wait(timeout=5)
        assert future.result(timeout=15) == "forbidden"
    workspace.refresh_from_db()
    assert workspace.name == "Original"


def test_concurrency_workspace_delete_does_not_invert_board_lock_order():
    user = User.objects.create_user("owner@example.com")
    workspace = create_workspace(user=user, name="Original", slug="original")
    actor = workspace.memberships.get(user=user)
    project = Project.objects.create(workspace=workspace, name="Project")
    task = create_task(
        column=project.board.columns.first(),
        actor=actor,
        title="Task",
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )
    workspace_locked = Event()

    def observe_lock(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if 'FROM "workspaces_workspace"' in sql and "FOR UPDATE" in sql:
            workspace_locked.set()
        return result

    def delete():
        with connection.execute_wrapper(observe_lock):
            delete_workspace(workspace=workspace, actor=actor, confirmation="Original")

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            Project.objects.select_for_update().get(pk=project.pk)
            future = executor.submit(worker, delete)
            assert workspace_locked.wait(timeout=5)
            update_task(
                task=task,
                actor=actor,
                title="Changed",
                description="",
                priority=task.priority,
                due_date=None,
                assignee=None,
            )
        future.result(timeout=15)
    assert not Workspace.objects.filter(pk=workspace.pk).exists()
    assert not Task.objects.filter(pk=task.pk).exists()


def test_concurrency_invitation_acceptance_and_workspace_delete_commit_safely():
    owner = User.objects.create_user("owner@example.com")
    invited = User.objects.create_user("invited@example.com")
    workspace = create_workspace(user=owner, name="Original", slug="original")
    actor = workspace.memberships.get(user=owner)
    _, token = create_invitation(
        workspace=workspace, actor=actor, email=invited.email, role="member"
    )
    barrier = Barrier(2)

    def delete():
        barrier.wait(timeout=5)
        delete_workspace(workspace=workspace, actor=actor, confirmation="Original")

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            accept_invitation(token=token, user=invited)
            future = executor.submit(worker, delete)
            barrier.wait(timeout=5)
        future.result(timeout=15)
    assert not Workspace.objects.filter(pk=workspace.pk).exists()
