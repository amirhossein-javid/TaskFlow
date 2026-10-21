from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.db import close_old_connections, connection

from apps.accounts.models import User
from apps.boards.models import Task
from apps.boards.services import create_task
from apps.projects.models import Project
from apps.workspaces.models import WorkspaceMembership
from apps.workspaces.services import create_workspace

pytestmark = pytest.mark.django_db(transaction=True)


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
