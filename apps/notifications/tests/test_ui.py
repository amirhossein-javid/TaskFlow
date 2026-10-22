import pytest
from django.contrib.auth.models import AnonymousUser
from django.test import RequestFactory
from django.urls import reverse

from apps.boards.models import TaskActivity
from apps.boards.services import create_task_comment
from apps.notifications.context_processors import notification_navigation
from apps.notifications.models import Notification
from apps.notifications.services import mark_all_notifications_read

pytestmark = pytest.mark.django_db


def test_navigation_counter_uses_one_query_and_no_anonymous_queries(
    context, assigned_task, django_assert_num_queries
):
    request = RequestFactory().get("/")
    request.user = AnonymousUser()
    with django_assert_num_queries(0):
        assert notification_navigation(request) == {}
        assert not Notification.objects.visible_to(request.user).exists()
    request.user = context["member"].user
    with django_assert_num_queries(1):
        assert notification_navigation(request)["notification_unread_count"] == 1
    mark_all_notifications_read(user=request.user)
    assert notification_navigation(request)["notification_unread_count"] == 0
    create_task_comment(task=assigned_task, actor=context["actor"], body="Later")
    assert notification_navigation(request)["notification_unread_count"] == 1
    context["member"].delete()
    assert notification_navigation(request)["notification_unread_count"] == 0


def test_bell_inbox_rtl_and_escaped_history(client, context, assigned_task):
    url = reverse("notifications:inbox")
    assert 'class="icon-button notification-bell"' not in client.get("/").content.decode()
    client.force_login(context["member"].user)
    note = Notification.objects.get()
    TaskActivity.objects.filter(pk=note.activity_id).update(task_title="<script>alert(1)</script>")
    response = client.get(url)
    html = response.content.decode()
    assert 'dir="rtl"' in html
    assert 'aria-label="اعلان‌ها، 1 خوانده‌نشده"' in html
    assert 'class="notification-card is-unread"' in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html
    assert "<script>alert(1)</script>" not in html
    assert response.context["notification_unread_count"] == 1
    client.post(reverse("notifications:read_all"))
    html = client.get(url).content.decode()
    assert 'aria-label="اعلان‌ها، 0 خوانده‌نشده"' in html
    assert 'class="notification-card is-unread"' not in html
    assert "خوانده‌شده" in html
    assert "اعلانی برای نمایش وجود ندارد." in client.get(url + "?unread=1").content.decode()


@pytest.mark.parametrize("role", ["owner", "admin", "member"])
def test_all_roles_have_same_notification_task_visibility(client, context, assigned_task, role):
    membership = context["member"]
    membership.role = role
    membership.save(update_fields=["role"])
    client.force_login(membership.user)
    response = client.get(reverse("notifications:inbox"))
    assert response.context["paginator"].count == 1
    assert response.context["notification_unread_count"] == 1
    task_url = reverse(
        "boards:task_detail",
        args=[membership.workspace.slug, context["board"].project_id, assigned_task.pk],
    )
    assert client.get(task_url).status_code == 200
