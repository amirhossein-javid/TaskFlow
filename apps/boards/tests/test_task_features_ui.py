import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import connection
from django.test.utils import CaptureQueriesContext

from apps.accounts.models import User
from apps.boards.models import ChecklistItem, ProjectLabel, TaskChecklist
from apps.boards.services import (
    create_checklist,
    create_checklist_item,
    set_checklist_item_completed,
    set_task_label,
    update_project_label,
)
from apps.workspaces.models import WorkspaceMembership

from .test_labels import label_context as label_context
from .test_labels import url

pytestmark = pytest.mark.django_db


@pytest.fixture
def features(label_context):
    board, owner, member, task, label = label_context
    other = ProjectLabel.objects.create(project=board.project, name="Feature", color="green")
    for item in [label, other]:
        set_task_label(task=task, label=item, actor=member, attached=True)
    first = create_checklist(task=task, actor=member, title="Release")
    second = create_checklist(task=task, actor=member, title="Review")
    create_checklist(task=task, actor=member, title="Empty")
    item = create_checklist_item(checklist=first, actor=member, text="Build")
    create_checklist_item(checklist=first, actor=member, text="Test")
    create_checklist_item(checklist=second, actor=member, text="Review")
    set_checklist_item_completed(item=item, actor=member, completed=True)
    return label_context, first, item


def test_kanban_counts_are_not_multiplied_by_labels_and_do_not_change_positions(client, features):
    context, _, _ = features
    task = context[3]
    original = (task.column_id, task.position)
    for params in [{}, {"sort": "priority_desc"}, {"q": "Task"}, {"priority": "invalid"}]:
        response = client.get(url(context, "detail"), params)
        assert response.status_code == 200
        html = response.content.decode()
        if params.get("priority") == "invalid":
            assert "Bug" not in html
            continue
        displayed = list(response.context["columns"][0].tasks.all())[0]
        assert (displayed.checklist_completed, displayed.checklist_total) == (1, 3)
        assert "Bug" in html and "Feature" in html
        assert 'max="3"' in html
        assert 'aria-label="پیشرفت چک‌لیست‌های Task"' in html
        assert ('draggable="true"' in html) == (not params)
    task.refresh_from_db()
    assert (task.column_id, task.position) == original


def test_task_detail_shows_checklists_progress_and_snapshot_history(client, features):
    context, checklist, item = features
    response = client.get(url(context, "task_detail", context[3].pk))
    html = response.content.decode()
    assert response.status_code == 200
    assert "Bug" in html and "Feature" in html
    assert "این چک‌لیست هنوز موردی ندارد." in html
    assert 'max="0"' not in html
    assert "بازگشایی مورد Build" in html
    assert "انجام مورد Test" in html
    assert 'name="completed" value="false"' in html
    assert list(response.context["checklists"])[0].item_total == 2
    assert response.context["comment_page"].number == 1
    assert response.context["activity_page"].number == 1
    assert "برچسب به وظیفه افزوده شد" in html
    assert "مورد چک‌لیست انجام شد" in html
    assert f'aria-labelledby="checklist-heading-{checklist.pk}"' in html
    assert item.text in html


@pytest.mark.parametrize("page", ["detail", "task_detail"])
def test_features_do_not_introduce_n_plus_one_queries(client, features, page):
    context, _, _ = features
    board, _, _, task, _ = context
    endpoint = url(context, page, *([task.pk] if page == "task_detail" else []))
    with CaptureQueriesContext(connection) as before:
        assert client.get(endpoint).status_code == 200
    for index in range(8):
        label = ProjectLabel.objects.create(
            project=board.project, name=f"Label {index}", color="blue"
        )
        task.labels.add(label)
        checklist = TaskChecklist.objects.create(task=task, title=f"List {index}")
        ChecklistItem.objects.bulk_create(
            [ChecklistItem(checklist=checklist, text=f"Item {number}") for number in range(10)]
        )
    with CaptureQueriesContext(connection) as after:
        assert client.get(endpoint).status_code == 200
    assert len(after) == len(before)


def test_archived_task_features_are_visible_without_mutation_controls(client, features):
    context, _, _ = features
    project = context[0].project
    project.status = "archived"
    project.save(update_fields=["status"])
    html = client.get(url(context, "task_detail", context[3].pk)).content.decode()
    assert "Release" in html and "Bug" in html
    assert "1 از 2 مورد انجام شده" in html
    assert "/checklists/" not in html
    assert 'name="attached"' not in html
    assert 'name="completed"' not in html


@pytest.mark.parametrize("role", WorkspaceMembership.Role.values)
def test_workspace_roles_can_manage_shared_checklists(client, features, role):
    context, _, item = features
    user = User.objects.create_user(f"{role}@example.com")
    WorkspaceMembership.objects.create(workspace=context[0].project.workspace, user=user, role=role)
    client.force_login(user)
    assert (
        client.post(
            url(context, "checklist_item_state", context[3].pk, item.checklist_id, item.pk),
            {"completed": "false"},
        ).status_code
        == 302
    )
    item.refresh_from_db()
    assert not item.is_completed


@pytest.mark.parametrize("name", ["projectlabel", "tasklabel", "taskchecklist", "checklistitem"])
def test_feature_admins_are_read_only(client, features, name):
    from django.urls import reverse

    context, checklist, item = features
    admin = User.objects.create_superuser("feature-admin@example.com", "SecurePass123!")
    client.force_login(admin)
    objects = {
        "projectlabel": context[4],
        "tasklabel": context[3].label_links.first(),
        "taskchecklist": checklist,
        "checklistitem": item,
    }
    instance = objects[name]
    assert client.get(reverse(f"admin:boards_{name}_add")).status_code == 403
    assert client.get(reverse(f"admin:boards_{name}_change", args=[instance.pk])).status_code == 200
    assert (
        client.post(reverse(f"admin:boards_{name}_change", args=[instance.pk]), {}).status_code
        == 403
    )
    assert (
        client.post(
            reverse(f"admin:boards_{name}_delete", args=[instance.pk]), {"post": "yes"}
        ).status_code
        == 403
    )


@pytest.mark.parametrize("role", ["owner", "admin"])
def test_managers_can_manage_project_labels_without_task_event_fanout(client, label_context, role):
    context = label_context
    actor = context[1]
    actor.role = role
    actor.save(update_fields=["role"])
    before = context[3].activities.count()
    assert (
        client.post(
            url(context, "label_create"), {"name": "Another", "color": "purple"}
        ).status_code
        == 302
    )
    assert (
        client.post(
            url(context, "label_edit", context[4].pk), {"name": "Updated", "color": "gray"}
        ).status_code
        == 302
    )
    assert client.post(url(context, "label_delete", context[4].pk)).status_code == 302
    assert context[3].activities.count() == before


def test_removed_membership_cannot_mutate_features(features):
    context, _, item = features
    _, _, member, task, label = context
    member_id = member.pk
    member.delete()
    member.pk = member_id
    with pytest.raises(PermissionDenied):
        set_task_label(task=task, label=label, actor=member, attached=False)
    with pytest.raises(PermissionDenied):
        set_checklist_item_completed(item=item, actor=member, completed=False)


def test_catalog_edit_does_not_lock_attached_tasks(features):
    from unittest.mock import patch

    from apps.boards.models import Task

    context, _, _ = features
    with patch.object(Task.objects, "select_for_update") as lock_tasks:
        update_project_label(label=context[4], actor=context[1], name="Renamed", color="purple")
    lock_tasks.assert_not_called()


def test_deleted_items_are_not_resurrected_by_stale_state_updates(features):
    context, _, item = features
    ChecklistItem.objects.filter(pk=item.pk).delete()
    with pytest.raises(ValidationError):
        set_checklist_item_completed(item=item, actor=context[2], completed=False)


def test_new_endpoints_preserve_authentication_scoping_and_method_order(client, features):
    context, checklist, item = features
    endpoints = [
        url(context, "label_create"),
        url(context, "label_edit", context[4].pk),
        url(context, "label_delete", context[4].pk),
        url(context, "task_label", context[3].pk),
        url(context, "checklist_create", context[3].pk),
        url(context, "checklist_edit", context[3].pk, checklist.pk),
        url(context, "checklist_delete", context[3].pk, checklist.pk),
        url(context, "checklist_item_create", context[3].pk, checklist.pk),
        url(context, "checklist_item_edit", context[3].pk, checklist.pk, item.pk),
        url(context, "checklist_item_delete", context[3].pk, checklist.pk, item.pk),
        url(context, "checklist_item_state", context[3].pk, checklist.pk, item.pk),
    ]
    outsider = User.objects.create_user("feature-outsider@example.com")
    client.force_login(outsider)
    for endpoint in endpoints:
        assert client.post(endpoint, {}).status_code == 404
        response = client.put(endpoint, {})
        assert response.status_code == 405
        assert "POST" in response.headers["Allow"]
    client.logout()
    for endpoint in endpoints:
        assert client.post(endpoint, {}).status_code == 302
