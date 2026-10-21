import json

import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.boards.models import Task
from apps.boards.services import create_task
from apps.projects.models import Project
from apps.workspaces.models import WorkspaceMembership
from apps.workspaces.services import create_workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def context():
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


def board_url(context):
    return reverse(
        "boards:detail",
        args=[context["workspace"].slug, context["project"].pk],
    )


def make_task(context, *, title="Task"):
    return create_task(
        column=context["board"].columns.first(),
        actor=context["member_membership"],
        title=title,
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )


def test_board_requires_authentication(client, context):
    response = client.get(board_url(context))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_member_can_view_board_and_non_member_gets_404(client, context):
    client.force_login(context["member"])
    response = client.get(board_url(context))
    assert response.status_code == 200
    assert "برد کانبان" in response.content.decode()

    client.force_login(context["outsider"])
    assert client.get(board_url(context)).status_code == 404


def test_only_manager_can_create_column(client, context):
    url = reverse(
        "boards:column_create",
        args=[context["workspace"].slug, context["project"].pk],
    )
    client.force_login(context["member"])
    assert client.post(url, {"name": "Review"}).status_code == 403

    client.force_login(context["owner"])
    response = client.post(url, {"name": "بررسی"})
    assert response.status_code == 302
    assert context["board"].columns.filter(name="بررسی").exists()


def test_member_can_create_edit_and_delete_task(client, context):
    column = context["board"].columns.first()
    create_url = reverse(
        "boards:task_create",
        args=[context["workspace"].slug, context["project"].pk, column.pk],
    )
    client.force_login(context["member"])
    response = client.post(
        create_url,
        {
            "title": "New task",
            "description": "Details",
            "priority": Task.Priority.HIGH,
            "due_date": "",
            "assignee": context["member"].pk,
        },
    )
    task = Task.objects.get(title="New task")
    assert response.status_code == 302

    edit_url = reverse(
        "boards:task_edit",
        args=[context["workspace"].slug, context["project"].pk, task.pk],
    )
    response = client.post(
        edit_url,
        {
            "title": "Updated",
            "description": "",
            "priority": Task.Priority.LOW,
            "due_date": "",
            "assignee": "",
        },
    )
    task.refresh_from_db()
    assert response.status_code == 302
    assert task.title == "Updated"

    delete_url = reverse(
        "boards:task_delete",
        args=[context["workspace"].slug, context["project"].pk, task.pk],
    )
    assert client.post(delete_url).status_code == 302
    assert not Task.objects.filter(pk=task.pk).exists()


def test_task_form_rejects_assignee_from_another_workspace(client, context):
    column = context["board"].columns.first()
    client.force_login(context["member"])
    response = client.post(
        reverse(
            "boards:task_create",
            args=[context["workspace"].slug, context["project"].pk, column.pk],
        ),
        {
            "title": "Task",
            "description": "",
            "priority": Task.Priority.MEDIUM,
            "due_date": "",
            "assignee": context["outsider"].pk,
        },
    )

    assert response.status_code == 200
    assert "عضو این فضای کاری نیست" in response.content.decode()
    assert not Task.objects.filter(title="Task").exists()


def test_task_and_target_column_are_isolated_to_url_project(client, context):
    task = make_task(context)
    other_workspace = create_workspace(user=context["outsider"], name="Other", slug="other")
    other_project = Project.objects.create(
        workspace=other_workspace,
        name="Other project",
        creator=context["outsider"],
    )
    client.force_login(context["member"])

    foreign_task_url = reverse(
        "boards:task_detail",
        args=[context["workspace"].slug, context["project"].pk, 999999],
    )
    assert client.get(foreign_task_url).status_code == 404

    move_url = reverse(
        "boards:task_move",
        args=[context["workspace"].slug, context["project"].pk, task.pk],
    )
    response = client.post(
        move_url,
        data=json.dumps({"column": other_project.board.columns.first().pk, "position": 0}),
        content_type="application/json",
    )
    assert response.status_code == 404
    task.refresh_from_db()
    assert task.column.board == context["board"]


def test_archived_project_is_read_only(client, context):
    task = make_task(context)
    context["project"].status = Project.Status.ARCHIVED
    context["project"].save(update_fields=["status"])
    client.force_login(context["member"])

    create_url = reverse(
        "boards:task_create",
        args=[
            context["workspace"].slug,
            context["project"].pk,
            context["board"].columns.first().pk,
        ],
    )
    assert client.get(create_url).status_code == 302
    assert client.post(create_url, {"title": "Blocked"}).status_code == 302
    assert not Task.objects.filter(title="Blocked").exists()

    move_url = reverse(
        "boards:task_move",
        args=[context["workspace"].slug, context["project"].pk, task.pk],
    )
    response = client.post(
        move_url,
        data=json.dumps({"column": task.column_id, "position": 0}),
        content_type="application/json",
    )
    assert response.status_code == 400


def test_move_requires_post_and_csrf(context):
    task = make_task(context)
    url = reverse(
        "boards:task_move",
        args=[context["workspace"].slug, context["project"].pk, task.pk],
    )
    client = Client(enforce_csrf_checks=True)
    client.force_login(context["member"])

    assert client.get(url).status_code == 405
    assert (
        client.post(
            url,
            data=json.dumps({"column": task.column_id, "position": 0}),
            content_type="application/json",
        ).status_code
        == 403
    )
