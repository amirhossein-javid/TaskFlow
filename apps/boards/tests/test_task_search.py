from datetime import date

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.boards.forms import TaskFilterForm
from apps.boards.models import Task
from apps.projects.models import Project
from apps.workspaces.models import WorkspaceMembership
from apps.workspaces.services import create_workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def search_board(client):
    owner = User.objects.create_user(email="search@example.com", password="SecurePass123!")
    workspace = create_workspace(user=owner, name="Search", slug="search")
    project = Project.objects.create(workspace=workspace, name="Search", creator=owner)
    board = project.board
    columns = list(board.columns.all())
    tasks = [
        Task.objects.create(
            column=columns[index % 2],
            position=index // 2,
            title=title,
            description=description,
            priority=priority,
            due_date=due,
            assignee=assignee,
        )
        for index, (title, description, priority, due, assignee) in enumerate(
            [
                ("طراحی", "صفحهٔ نخست", "high", date(2026, 10, 22), owner),
                ("بررسی", "طراحی API", "low", date(2026, 10, 23), None),
                ("Release", "Deploy API", "medium", None, None),
            ]
        )
    ]
    client.force_login(owner)
    return board, workspace, owner, columns, tasks


def board_url(board):
    return reverse("boards:detail", args=[board.project.workspace.slug, board.project_id])


def displayed_tasks(response):
    return [task for column in response.context["columns"] for task in column.tasks.all()]


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"q": " طراحی "}, [0, 1]),
        ({"q": "api"}, [2, 1]),
        ({"priority": "high"}, [0]),
        ({"assignee": "unassigned"}, [2, 1]),
        ({"due_from": "2026-10-22", "due_to": "2026-10-22"}, [0]),
        ({"q": "طراحی", "priority": "low", "due_to": "2026-10-23"}, [1]),
    ],
)
def test_task_filters(client, search_board, params, expected):
    board, _, _, columns, tasks = search_board
    response = client.get(board_url(board), params)
    assert response.status_code == 200
    assert [task.pk for task in displayed_tasks(response)] == [tasks[i].pk for i in expected]
    assert list(response.context["columns"]) == columns
    assert response.context["has_active_filters"]
    assert not response.context["can_move"]


@pytest.mark.parametrize(
    "params",
    [
        {"priority": "urgent"},
        {"column": "999999"},
        {"assignee": "999999"},
        {"sort": "title"},
        {"due_from": "bad"},
        {"due_from": "2026-10-23", "due_to": "2026-10-22"},
        {"q": "x" * 201},
    ],
)
def test_invalid_filters_never_return_unfiltered_tasks(client, search_board, params):
    board, *_ = search_board
    response = client.get(board_url(board), params)
    assert response.status_code == 200
    assert response.context["filter_form"].errors
    assert displayed_tasks(response) == []
    assert not response.context["can_move"]


def test_assignee_choices_include_only_members_and_board_assignees(client, search_board):
    board, workspace, owner, _, tasks = search_board
    former = User.objects.create_user(email="former@example.com")
    inactive = User.objects.create_user(email="inactive@example.com", is_active=False)
    unrelated = User.objects.create_user(email="unrelated@example.com")
    WorkspaceMembership.objects.create(
        workspace=workspace, user=inactive, role=WorkspaceMembership.Role.MEMBER
    )
    Task.objects.filter(pk=tasks[0].pk).update(assignee=former)
    other = Project.objects.create(workspace=workspace, name="Other", creator=owner)
    Task.objects.create(
        column=other.board.columns.first(), title="Other", position=0, assignee=unrelated
    )
    form = TaskFilterForm({}, board=board, workspace=workspace)
    assert {value for value, _ in form.fields["assignee"].choices} == {
        "",
        "unassigned",
        str(owner.pk),
        str(inactive.pk),
        str(former.pk),
    }
    response = client.get(board_url(board), {"assignee": former.pk})
    assert [task.pk for task in displayed_tasks(response)] == [tasks[0].pk]
    response = client.get(board_url(board), {"column": other.board.columns.first().pk})
    assert displayed_tasks(response) == []
    assert response.context["filter_form"].errors


def test_default_view_preserves_manual_order(client, search_board):
    board, _, _, _, tasks = search_board
    response = client.get(board_url(board))
    assert [task.pk for task in displayed_tasks(response)] == [tasks[i].pk for i in [0, 2, 1]]
    assert response.context["can_move"]
    assert not response.context["has_active_filters"]


@pytest.mark.parametrize(
    ("sort", "first_column"),
    [
        ("created_asc", [0, 2]),
        ("created_desc", [2, 0]),
        ("due_asc", [0, 2]),
        ("due_desc", [0, 2]),
        ("priority_asc", [2, 0]),
        ("priority_desc", [0, 2]),
    ],
)
def test_sorting_is_scoped_to_each_column(client, search_board, sort, first_column):
    board, _, _, _, tasks = search_board
    response = client.get(board_url(board), {"sort": sort})
    columns = list(response.context["columns"])
    assert [task.pk for task in columns[0].tasks.all()] == [tasks[i].pk for i in first_column]
    assert list(columns[1].tasks.all()) == [tasks[1]]
    assert not response.context["can_move"]
