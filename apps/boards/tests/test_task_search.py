from datetime import UTC, date, datetime

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext
from django.urls import reverse

from apps.accounts.models import Profile, User
from apps.boards.forms import TaskFilterForm
from apps.boards.models import BoardColumn, Task, TaskActivity
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


@pytest.mark.parametrize("params", [{"q": "طراحی"}, {"sort": "due_asc"}, {"sort": "invalid"}])
def test_filtered_ui_disables_every_move_control(client, search_board, params):
    board, *_ = search_board
    response = client.get(board_url(board), params)
    html = response.content.decode()
    assert 'data-can-move="false"' in html
    assert 'draggable="true"' not in html
    assert "data-move-url=" not in html
    assert "/nudge/" not in html
    assert "/shift/" not in html
    assert "js/kanban.js" not in html
    assert "بازگشت به نمای کامل و ترتیب دستی" in html
    assert "/tasks/new/" in html


def test_default_ui_keeps_move_controls_and_get_filter_form(client, search_board):
    board, *_ = search_board
    html = client.get(board_url(board)).content.decode()
    assert 'data-can-move="true"' in html
    assert 'draggable="true"' in html
    assert "/nudge/" in html
    assert "/shift/" in html
    assert "js/kanban.js" in html
    assert f'method="get" action="{board_url(board)}"' in html
    assert f'href="{board_url(board)}">پاک‌کردن فیلترها</a>' in html


def test_filter_ui_preserves_values_counts_and_accessible_errors(client, search_board):
    board, _, _, columns, _ = search_board
    params = {
        "q": "طراحی",
        "priority": "high",
        "column": columns[0].pk,
        "due_from": "2026-10-22",
        "sort": "due_asc",
    }
    response = client.get(board_url(board), params)
    html = response.content.decode()
    for name, value in params.items():
        assert str(response.context["filter_form"][name].value()) == str(value)
    assert 'value="طراحی"' in html
    assert 'value="high" selected' in html
    assert 'value="due_asc" selected' in html
    assert html.count('aria-label="1 وظیفهٔ نمایش‌داده‌شده">1') == 1
    assert html.count('aria-label="0 وظیفهٔ نمایش‌داده‌شده">0') == 2
    assert "وظیفه‌ای برای نمایش با این تنظیمات وجود ندارد." in html

    html = client.get(board_url(board), {"priority": "invalid"}).content.decode()
    assert "اولویت انتخاب‌شده معتبر نیست." in html
    assert "تا اصلاح آن‌ها هیچ وظیفه‌ای نمایش داده نمی‌شود." in html
    assert 'aria-invalid="true"' in html
    assert 'aria-describedby="id_priority_error"' in html
    assert 'id="id_priority_error"' in html


@pytest.mark.parametrize(
    ("params", "expected"),
    [
        ({"due_from": "2026-10-23"}, [1]),
        ({"due_to": "2026-10-22"}, [0]),
        ({"q": "missing"}, []),
        ({"q": "%"}, []),
        ({"q": "_"}, []),
    ],
)
def test_search_literals_and_open_date_ranges(client, search_board, params, expected):
    board, _, _, _, tasks = search_board
    response = client.get(board_url(board), params)
    assert [task.pk for task in displayed_tasks(response)] == [tasks[i].pk for i in expected]


@pytest.mark.parametrize(
    "params",
    [
        {"column": "not-an-id"},
        {"column": "9" * 100},
        {"due_to": "2026-02-30"},
        {"due_from": "22/10/2026"},
        {"q": "api", "priority": "invalid"},
    ],
)
def test_malformed_and_partially_valid_filters_show_persian_errors(client, search_board, params):
    board, *_ = search_board
    response = client.get(board_url(board), params)
    assert response.status_code == 200
    assert displayed_tasks(response) == []
    errors = response.context["filter_form"].errors.as_text()
    assert any("\u0600" <= character <= "\u06ff" for character in errors)
    assert "تا اصلاح آن‌ها هیچ وظیفه‌ای نمایش داده نمی‌شود." in response.content.decode()


def test_empty_filter_values_restore_manual_view_and_escape_search(client, search_board):
    board, *_ = search_board
    response = client.get(
        board_url(board),
        {
            "q": "   ",
            "column": "",
            "priority": "",
            "assignee": "",
            "due_from": "",
            "due_to": "",
            "sort": "",
        },
    )
    assert response.context["can_move"]
    assert len(displayed_tasks(response)) == 3
    response = client.get(board_url(board), {"q": '<script>alert("x")</script>'})
    assert '<script>alert("x")</script>' not in response.content.decode()
    assert "&lt;script&gt;" in response.content.decode()


@pytest.mark.parametrize(
    ("sort", "expected"),
    [
        ("created_asc", [0, 4, 3, 2]),
        ("created_desc", [2, 3, 0, 4]),
        ("due_asc", [0, 4, 3, 2]),
        ("due_desc", [3, 0, 4, 2]),
        ("priority_asc", [3, 2, 0, 4]),
        ("priority_desc", [0, 4, 2, 3]),
    ],
)
def test_sort_ties_null_dates_and_read_only_state(client, search_board, sort, expected):
    board, _, _, columns, tasks = search_board
    tasks.extend(
        [
            Task.objects.create(
                column=columns[0],
                title="Later low",
                position=2,
                priority="low",
                due_date=date(2026, 10, 23),
            ),
            Task.objects.create(
                column=columns[0],
                title="Tied high",
                position=3,
                priority="high",
                due_date=date(2026, 10, 22),
            ),
        ]
    )
    Task.objects.filter(column__board=board).update(created_at=datetime(2026, 10, 20, tzinfo=UTC))
    Task.objects.filter(pk=tasks[2].pk).update(created_at=datetime(2026, 10, 22, tzinfo=UTC))
    Task.objects.filter(pk=tasks[3].pk).update(created_at=datetime(2026, 10, 21, tzinfo=UTC))
    state = list(Task.objects.order_by("pk").values())
    history = list(TaskActivity.objects.order_by("pk").values())
    response = client.get(board_url(board), {"sort": sort})
    assert [task.pk for task in response.context["columns"][0].tasks.all()] == [
        tasks[index].pk for index in expected
    ]
    assert list(response.context["columns"][1].tasks.all()) == [tasks[1]]
    assert list(Task.objects.order_by("pk").values()) == state
    assert list(TaskActivity.objects.order_by("pk").values()) == history


@pytest.mark.parametrize("same_workspace", [True, False])
def test_search_and_choices_do_not_leak_other_boards(client, search_board, same_workspace):
    board, workspace, _, _, _ = search_board
    unrelated = User.objects.create_user(email="foreign@example.com")
    if not same_workspace:
        workspace = create_workspace(user=unrelated, name="Foreign", slug="foreign")
    project = Project.objects.create(workspace=workspace, name="Foreign")
    column = project.board.columns.first()
    Task.objects.create(column=column, title="Private foreign task", position=0, assignee=unrelated)
    response = client.get(board_url(board), {"q": "Private foreign"})
    assert displayed_tasks(response) == []
    assert unrelated.email not in response.content.decode()
    for params in [{"column": column.pk}, {"assignee": unrelated.pk}]:
        response = client.get(board_url(board), params)
        assert displayed_tasks(response) == []
        assert response.context["filter_form"].errors


@pytest.mark.parametrize("role", WorkspaceMembership.Role.values)
def test_all_workspace_roles_can_search_archived_boards(client, search_board, role):
    board, workspace, _, _, tasks = search_board
    member = User.objects.create_user(email="reader@example.com")
    WorkspaceMembership.objects.create(workspace=workspace, user=member, role=role)
    board.project.status = Project.Status.ARCHIVED
    board.project.save(update_fields=["status"])
    client.force_login(member)
    response = client.get(board_url(board), {"q": "طراحی", "sort": "priority_desc"})
    assert response.status_code == 200
    assert [task.pk for task in displayed_tasks(response)] == [tasks[0].pk, tasks[1].pk]
    html = response.content.decode()
    assert not response.context["can_move"]
    assert 'draggable="true"' not in html
    assert "/nudge/" not in html
    assert "/shift/" not in html
    assert "/tasks/new/" not in html
    assert "js/kanban.js" not in html
    assert "برد و وظیفه‌ها فقط قابل مشاهده‌اند." in html


def test_filter_requests_preserve_authentication_scope_and_method_contracts(client, search_board):
    board, *_ = search_board
    url = board_url(board)
    params = {"priority": "invalid"}
    assert client.head(url, params).status_code == 200
    missing = reverse("boards:detail", args=["missing", 999999])
    for target in [url, missing]:
        for method in ["post", "put", "patch", "delete", "options"]:
            response = getattr(client, method)(target, params)
            assert response.status_code == 405
            assert response.headers["Allow"] == "GET, HEAD"
    outsider = User.objects.create_user(email="outsider@example.com")
    client.force_login(outsider)
    assert client.get(url, params).status_code == 404
    client.logout()
    response = client.get(url, params)
    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


@pytest.mark.parametrize("params", [{}, {"q": "api", "sort": "priority_desc"}])
def test_board_query_count_does_not_grow_with_columns_tasks_or_assignees(
    client, search_board, params
):
    board, workspace, _, _, _ = search_board
    with CaptureQueriesContext(connection) as small:
        assert client.get(board_url(board), params).status_code == 200
    columns = BoardColumn.objects.bulk_create(
        [BoardColumn(board=board, name=f"Column {index}", position=index) for index in range(3, 8)]
    )
    for index, column in enumerate(columns):
        user = User.objects.create_user(email=f"assignee-{index}@example.com")
        WorkspaceMembership.objects.create(
            workspace=workspace, user=user, role=WorkspaceMembership.Role.MEMBER
        )
        Task.objects.bulk_create(
            [
                Task(column=column, title=f"API task {position}", position=position, assignee=user)
                for position in range(20)
            ]
        )
    with CaptureQueriesContext(connection) as large:
        response = client.get(board_url(board), params)
        assert response.status_code == 200
    assert len(large) == len(small)
    assert len(displayed_tasks(response)) >= 100


@pytest.mark.parametrize("is_member", [True, False])
def test_missing_profiles_fall_back_to_email_without_extra_queries(client, search_board, is_member):
    board, workspace, _, _, tasks = search_board
    with CaptureQueriesContext(connection) as before:
        assert client.get(board_url(board)).status_code == 200
    users = User.objects.bulk_create(
        [User(email=f"missing-profile-{index}@example.com") for index in range(3)]
    )
    if is_member:
        WorkspaceMembership.objects.bulk_create(
            [
                WorkspaceMembership(
                    workspace=workspace, user=user, role=WorkspaceMembership.Role.MEMBER
                )
                for user in users
            ]
        )
    for task, user in zip(tasks, users, strict=True):
        Task.objects.filter(pk=task.pk).update(assignee=user)
    with CaptureQueriesContext(connection) as after:
        response = client.get(board_url(board))
        assert response.status_code == 200
    assert len(after) == len(before)
    choices = dict(response.context["filter_form"].fields["assignee"].choices)
    for user in users:
        assert choices[str(user.pk)] == user.email
        assert user.email in response.content.decode()
    response = client.get(board_url(board), {"assignee": users[0].pk, "q": "طراحی"})
    assert response.status_code == 200
    assert [task.pk for task in displayed_tasks(response)] == [tasks[0].pk]
    assert not Profile.objects.filter(user__in=users).exists()
