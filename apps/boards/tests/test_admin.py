import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.boards.models import Task, TaskActivity
from apps.boards.services import create_task, create_task_comment
from apps.projects.models import Project
from apps.workspaces.services import create_workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def admin_context():
    admin_user = User.objects.create_superuser(
        email="readonly-admin@example.com",
        password="SecurePass123!",
    )
    workspace = create_workspace(user=admin_user, name="Admin", slug="admin")
    membership = workspace.memberships.get(user=admin_user)
    project = Project.objects.create(
        workspace=workspace,
        name="Archived project",
        creator=admin_user,
    )
    task = create_task(
        column=project.board.columns.first(),
        actor=membership,
        title="Protected task",
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=None,
    )
    comment = create_task_comment(task=task, actor=membership, body="Protected comment")
    project.status = Project.Status.ARCHIVED
    project.save(update_fields=["status"])
    return admin_user, project, task, comment, task.activities.first()


@pytest.mark.parametrize(
    ("model_name", "object_index"),
    [("task", 2), ("taskcomment", 3), ("taskactivity", 4)],
)
def test_collaboration_admins_are_strictly_read_only(
    client,
    admin_context,
    model_name,
    object_index,
):
    admin_user, _project, _task, _comment, _activity = admin_context
    client.force_login(admin_user)
    instance = admin_context[object_index]
    model = instance.__class__
    original_count = model.objects.count()
    original_values = model.objects.filter(pk=instance.pk).values().get()
    changelist_url = reverse(f"admin:boards_{model_name}_changelist")
    change_url = reverse(f"admin:boards_{model_name}_change", args=[instance.pk])
    add_url = reverse(f"admin:boards_{model_name}_add")
    delete_url = reverse(f"admin:boards_{model_name}_delete", args=[instance.pk])

    assert client.get(changelist_url).status_code == 200
    assert client.get(change_url).status_code == 200
    assert client.get(add_url).status_code == 403
    assert client.post(change_url, {"title": "Bypassed"}).status_code == 403
    assert client.get(delete_url).status_code == 403
    assert client.post(delete_url, {"post": "yes"}).status_code == 403

    bulk_response = client.post(
        changelist_url,
        {
            "action": "delete_selected",
            "_selected_action": [instance.pk],
            "index": "0",
        },
    )
    assert bulk_response.status_code == 200
    assert model.objects.count() == original_count
    assert model.objects.filter(pk=instance.pk).values().get() == original_values


def test_admin_cannot_bypass_archived_project_or_create_activity(client, admin_context):
    admin_user, project, task, comment, _activity = admin_context
    client.force_login(admin_user)
    activity_count = TaskActivity.objects.filter(project=project).count()

    task_response = client.post(
        reverse("admin:boards_task_change", args=[task.pk]),
        {"title": "Changed through admin"},
    )
    comment_response = client.post(
        reverse("admin:boards_taskcomment_change", args=[comment.pk]),
        {"body": "Changed through admin"},
    )

    task.refresh_from_db()
    comment.refresh_from_db()
    assert task_response.status_code == 403
    assert comment_response.status_code == 403
    assert task.title == "Protected task"
    assert comment.body == "Protected comment"
    assert TaskActivity.objects.filter(project=project).count() == activity_count
