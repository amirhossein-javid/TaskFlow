import pytest
from django.test import Client
from django.urls import reverse

from apps.boards.models import TaskActivity
from apps.boards.services import create_task_comment
from apps.notifications.models import Notification
from apps.notifications.services import mark_all_notifications_read, set_notification_read
from apps.projects.models import Project
from apps.workspaces.models import WorkspaceMembership

pytestmark = pytest.mark.django_db


def inbox():
    return reverse("notifications:inbox")


def test_inbox_states_are_owned_and_idempotent(client, context, assigned_task):
    user = context["member"].user
    client.force_login(user)
    note = Notification.objects.get()
    assert client.get(inbox()).status_code == 200
    note.refresh_from_db()
    assert note.read_at is None
    url = reverse("notifications:read", args=[note.pk])
    assert client.post(url, {"next": "https://evil.example"}).url == inbox()
    note.refresh_from_db()
    first_read = note.read_at
    assert first_read is not None
    assert client.post(url).status_code == 302
    note.refresh_from_db()
    assert note.read_at == first_read
    response = client.get(inbox() + "?unread=1")
    assert not response.context["notifications"]
    assert client.post(reverse("notifications:unread", args=[note.pk])).status_code == 302
    assert client.post(reverse("notifications:unread", args=[note.pk])).status_code == 302
    note.refresh_from_db()
    assert note.read_at is None
    assert client.post(reverse("notifications:read_all")).status_code == 302
    assert mark_all_notifications_read(user=user) == 0
    create_task_comment(task=assigned_task, actor=context["actor"], body="Later")
    assert Notification.objects.filter(read_at__isnull=True).count() == 1


@pytest.mark.parametrize("name", ["read", "unread"])
def test_other_users_and_unsupported_methods_cannot_access_notification(
    client, context, assigned_task, name
):
    note = Notification.objects.get()
    url = reverse("notifications:" + name, args=[note.pk])
    assert client.post(url).status_code == 302
    client.force_login(context["outsider"])
    assert client.post(url).status_code == 404
    assert client.post(reverse("notifications:" + name, args=[999999])).status_code == 404
    for method in ["get", "head", "put", "delete", "options"]:
        response = getattr(client, method)(url)
        assert response.status_code == 405
        assert response.headers["Allow"] == "POST"
    assert client.get(inbox()).context["paginator"].count == 0
    assert client.post(reverse("notifications:read_all")).status_code == 302
    note.refresh_from_db()
    assert note.read_at is None


def test_inbox_http_contract_and_csrf(context, assigned_task):
    client = Client(enforce_csrf_checks=True)
    assert client.get(inbox()).status_code == 302
    client.force_login(context["member"].user)
    assert client.head(inbox()).status_code == 200
    response = client.post(inbox())
    assert response.status_code == 403
    csrf = client.cookies["csrftoken"].value
    response = client.post(inbox(), HTTP_X_CSRFTOKEN=csrf)
    assert response.status_code == 405
    assert response.headers["Allow"] == "GET, HEAD"
    note = Notification.objects.get()
    for name in ["read", "unread", "read_all"]:
        url = reverse("notifications:" + name, args=[] if name == "read_all" else [note.pk])
        assert client.post(url).status_code == 403
        assert client.post(url, HTTP_X_CSRFTOKEN=csrf).status_code == 302


def test_membership_loss_rejoin_and_archive_match_task_visibility(client, context, assigned_task):
    user = context["member"].user
    client.force_login(user)
    task_url = reverse(
        "boards:task_detail",
        args=[
            context["board"].project.workspace.slug,
            context["board"].project_id,
            assigned_task.pk,
        ],
    )
    note = Notification.objects.get()
    assert client.get(task_url).status_code == 200
    context["member"].delete()
    assert client.get(task_url).status_code == 404
    assert not Notification.objects.visible_to(user).exists()
    assert client.post(reverse("notifications:read", args=[note.pk])).status_code == 404
    assert mark_all_notifications_read(user=user) == 0
    WorkspaceMembership.objects.create(
        workspace=context["board"].project.workspace, user=user, role="admin"
    )
    assert client.get(task_url).status_code == 200
    assert Notification.objects.visible_to(user).count() == 1
    Project.objects.filter(pk=context["board"].project_id).update(status=Project.Status.ARCHIVED)
    assert client.get(task_url).status_code == 200
    assert client.post(reverse("notifications:read", args=[note.pk])).status_code == 302
    user.is_active = False
    user.save(update_fields=["is_active"])
    assert not Notification.objects.visible_to(user).exists()
    assert not Notification.objects.visible_to(context["outsider"]).exists()


def test_inconsistent_task_activity_scope_is_never_exposed(context, assigned_task):
    note = Notification.objects.get()
    project = Project.objects.create(
        workspace=context["board"].project.workspace, name="Other", creator=context["actor"].user
    )
    TaskActivity.objects.filter(pk=note.activity_id).update(project=project)
    assert not Notification.objects.visible_to(context["member"].user).exists()
    with pytest.raises(Notification.DoesNotExist):
        set_notification_read(user=context["member"].user, notification_id=note.pk, read=True)


def test_pagination_query_count_and_safe_task_links(
    client, context, assigned_task, django_assert_num_queries
):
    user = context["member"].user
    client.force_login(user)
    task_url = reverse(
        "boards:task_detail",
        args=[
            context["board"].project.workspace.slug,
            context["board"].project_id,
            assigned_task.pk,
        ],
    )
    response = client.get(inbox())
    assert task_url in response.content.decode()
    from django.db import connection
    from django.test.utils import CaptureQueriesContext

    with CaptureQueriesContext(connection) as first:
        client.get(inbox())
    for i in range(24):
        create_task_comment(task=assigned_task, actor=context["actor"], body=f"Comment {i}")
    with django_assert_num_queries(len(first)):
        response = client.get(inbox())
    assert response.context["paginator"].count == 25
    assert len(response.context["notifications"]) == 20
    assert len(client.get(inbox() + "?page=2").context["notifications"]) == 5
    assert "unread=1" in client.get(inbox() + "?unread=1").content.decode()
    assert client.get(inbox() + "?page=999").status_code == 404


@pytest.mark.parametrize("relation", ["recipient", "actor", "project"])
def test_related_deletion_lifecycle(context, assigned_task, relation):
    if relation == "recipient":
        context["member"].user.delete()
        assert not Notification.objects.exists()
    elif relation == "project":
        context["board"].project.delete()
        assert not Notification.objects.exists()
    else:
        context["actor"].user.delete()
        note = Notification.objects.get()
        assert note.activity.actor_id is None
        assert Notification.objects.visible_to(context["member"].user).count() == 1
