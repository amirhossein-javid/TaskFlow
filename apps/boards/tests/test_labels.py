from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.boards.models import ProjectLabel, Task, TaskActivity, TaskLabel
from apps.boards.services import (
    create_project_label,
    delete_project_label,
    set_task_label,
    update_project_label,
)
from apps.projects.models import Project
from apps.workspaces.models import WorkspaceMembership
from apps.workspaces.services import create_workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def label_context(client):
    owner = User.objects.create_user("labels@example.com")
    member = User.objects.create_user("label-member@example.com")
    workspace = create_workspace(user=owner, name="Labels", slug="labels")
    actor = workspace.memberships.get(user=owner)
    member_actor = WorkspaceMembership.objects.create(
        workspace=workspace, user=member, role="member"
    )
    project = Project.objects.create(workspace=workspace, name="Labels")
    board = project.board
    task = Task.objects.create(column=board.columns.first(), title="Task", position=0)
    label = create_project_label(board=board, actor=actor, name=" Bug ", color="red")
    client.force_login(owner)
    return board, actor, member_actor, task, label


def url(context, name, *ids):
    board = context[0]
    return reverse(f"boards:{name}", args=[board.project.workspace.slug, board.project_id, *ids])


def test_label_uniqueness_validation_and_multiple_assignments(label_context):
    board, actor, member, task, label = label_context
    assert label.name == "Bug"
    with pytest.raises(ValidationError):
        create_project_label(board=board, actor=actor, name="bug", color="blue")
    with pytest.raises(IntegrityError), transaction.atomic():
        ProjectLabel.objects.create(project=board.project, name="BUG", color="blue")
    for name, color in [(" ", "blue"), ("Other", "url(evil)")]:
        with pytest.raises(ValidationError):
            create_project_label(board=board, actor=actor, name=name, color=color)
    other = create_project_label(board=board, actor=actor, name="Feature", color="green")
    for item in [label, other, label]:
        set_task_label(task=task, label=item, actor=member, attached=True)
    assert task.labels.count() == 2
    assert task.activities.count() == 2
    assert task.activities.filter(
        metadata={"label_id": label.pk, "label_name": "Bug", "label_color": "red"}
    ).exists()
    for _ in range(2):
        set_task_label(task=task, label=label, actor=member, attached=False)
    assert task.activities.filter(event_type="label_detached").count() == 1
    with pytest.raises(IntegrityError), transaction.atomic():
        TaskLabel.objects.create(task=task, label=other)


def test_shared_label_changes_do_not_fan_out_activity(label_context):
    _, actor, _, task, label = label_context
    set_task_label(task=task, label=label, actor=actor, attached=True)
    snapshot = list(task.activities.values())
    update_project_label(label=label, actor=actor, name="Defect", color="blue")
    delete_project_label(label=label, actor=actor)
    assert not task.labels.exists()
    assert list(task.activities.values()) == snapshot


def test_label_activity_failure_rolls_back_assignment(label_context):
    _, actor, _, task, label = label_context
    with (
        patch.object(TaskActivity.objects, "create", side_effect=RuntimeError),
        pytest.raises(RuntimeError),
    ):
        set_task_label(task=task, label=label, actor=actor, attached=True)
    assert not task.labels.exists()


def test_label_scope_and_manager_permissions(client, label_context):
    board, actor, member, task, label = label_context
    foreign = Project.objects.create(workspace=board.project.workspace, name="Foreign")
    other = ProjectLabel.objects.create(project=foreign, name="Bug", color="red")
    with pytest.raises(ValidationError):
        TaskLabel(task=task, label=other).full_clean()
    with pytest.raises(ValidationError):
        set_task_label(task=task, label=other, actor=actor, attached=True)
    assert client.get(url(label_context, "label_edit", other.pk)).status_code == 404
    client.force_login(member.user)
    assert client.get(url(label_context, "label_list")).status_code == 200
    for operation in [
        lambda: create_project_label(board=board, actor=member, name="Denied", color="blue"),
        lambda: update_project_label(label=label, actor=member, name="Denied", color="blue"),
        lambda: delete_project_label(label=label, actor=member),
    ]:
        with pytest.raises(PermissionDenied):
            operation()
    assert (
        client.post(
            url(label_context, "label_create"), {"name": "Denied", "color": "blue"}
        ).status_code
        == 403
    )
    assert (
        client.post(
            url(label_context, "task_label", task.pk), {"label": label.pk, "attached": "true"}
        ).status_code
        == 302
    )
    assert task.labels.count() == 1


def test_label_forms_http_contracts_archiving_and_csrf(client, label_context):
    board, actor, _, task, label = label_context
    assert client.head(url(label_context, "label_list")).status_code == 200
    create = url(label_context, "label_create")
    assert client.get(create).status_code == 200
    assert client.post(create, {"name": "New", "color": "green"}).status_code == 302
    assert client.post(create, {"name": "new", "color": "green"}).status_code == 200
    edit = url(label_context, "label_edit", label.pk)
    assert client.post(edit, {"name": "Changed", "color": "amber"}).status_code == 302
    delete = url(label_context, "label_delete", label.pk)
    assert client.get(delete).status_code == 200
    move = url(label_context, "task_label", task.pk)
    assert client.get(move).status_code == 405
    assert client.put(url(label_context, "label_edit", 999999)).status_code == 405
    protected = Client(enforce_csrf_checks=True)
    protected.force_login(actor.user)
    assert protected.post(move, {"label": label.pk, "attached": "true"}).status_code == 403
    board.project.status = "archived"
    board.project.save(update_fields=["status"])
    for operation in [
        lambda: create_project_label(board=board, actor=actor, name="Blocked", color="blue"),
        lambda: update_project_label(label=label, actor=actor, name="Blocked", color="blue"),
        lambda: delete_project_label(label=label, actor=actor),
        lambda: set_task_label(task=task, label=label, actor=actor, attached=True),
    ]:
        with pytest.raises(ValidationError):
            operation()
    assert client.get(create).status_code == 302
    assert client.post(delete).status_code == 302
    assert ProjectLabel.objects.filter(pk=label.pk).exists()
