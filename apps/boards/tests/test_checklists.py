from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.test import Client

from apps.boards.models import ChecklistItem, Task, TaskActivity, TaskChecklist
from apps.boards.services import (
    create_checklist,
    create_checklist_item,
    delete_checklist,
    delete_checklist_item,
    set_checklist_item_completed,
    update_checklist,
    update_checklist_item,
)

from .test_labels import label_context as label_context
from .test_labels import url

pytestmark = pytest.mark.django_db


@pytest.fixture
def checklist_context(label_context):
    _, _, member, task, _ = label_context
    checklist = create_checklist(task=task, actor=member, title=" Release ")
    item = create_checklist_item(checklist=checklist, actor=member, text=" Verify ")
    return label_context, checklist, item


def test_checklist_changes_and_no_ops_record_precise_history(checklist_context):
    context, checklist, item = checklist_context
    _, _, member, task, _ = context
    assert (checklist.title, item.text, item.is_completed) == ("Release", "Verify", False)
    update_checklist(checklist=checklist, actor=member, title=" Release ")
    update_checklist_item(item=item, actor=member, text=" Verify ")
    set_checklist_item_completed(item=item, actor=member, completed=False)
    assert task.activities.count() == 2
    update_checklist(checklist=checklist, actor=member, title="Launch")
    update_checklist_item(item=item, actor=member, text="Verified")
    set_checklist_item_completed(item=item, actor=member, completed=True)
    set_checklist_item_completed(item=item, actor=member, completed=True)
    assert task.activities.get(event_type="checklist_item_completed").metadata == {
        "checklist_id": checklist.pk,
        "checklist_title": "Launch",
        "item_id": item.pk,
        "item_text": "Verified",
        "is_completed": True,
    }
    assert task.activities.get(event_type="checklist_updated").metadata == {
        "checklist_id": checklist.pk,
        "checklist_title": "Launch",
        "previous_title": "Release",
    }
    assert (
        task.activities.get(event_type="checklist_item_updated").metadata["previous_text"]
        == "Verify"
    )
    set_checklist_item_completed(item=item, actor=member, completed=False)
    assert task.activities.filter(event_type="checklist_item_reopened").count() == 1
    delete_checklist_item(item=item, actor=member)
    assert not ChecklistItem.objects.filter(pk=item.pk).exists()
    assert (
        task.activities.get(event_type="checklist_item_deleted").metadata["item_text"] == "Verified"
    )
    another = create_checklist(task=task, actor=member, title="Other")
    create_checklist_item(checklist=another, actor=member, text="Child")
    before = task.activities.count()
    delete_checklist(checklist=another, actor=member)
    assert task.activities.count() == before + 1
    assert task.activities.get(event_type="checklist_deleted").metadata["item_count"] == 1


def test_checklist_validation_and_database_constraints(checklist_context):
    context, checklist, item = checklist_context
    _, _, member, task, _ = context
    for operation in [
        lambda: create_checklist(task=task, actor=member, title=" "),
        lambda: update_checklist(checklist=checklist, actor=member, title="x" * 101),
        lambda: create_checklist_item(checklist=checklist, actor=member, text=" "),
        lambda: update_checklist_item(item=item, actor=member, text="x" * 301),
        lambda: set_checklist_item_completed(item=item, actor=member, completed="false"),
    ]:
        with pytest.raises(ValidationError):
            operation()
    with pytest.raises(IntegrityError), transaction.atomic():
        TaskChecklist.objects.create(task=task, title=" ")
    with pytest.raises(IntegrityError), transaction.atomic():
        ChecklistItem.objects.create(checklist=checklist, text=" ")


@pytest.mark.parametrize("operation", ["create", "edit", "state", "delete", "delete_checklist"])
def test_checklist_activity_failures_roll_back_changes(checklist_context, operation):
    context, checklist, item = checklist_context
    _, _, member, task, _ = context
    before = list(ChecklistItem.objects.values())
    actions = {
        "create": lambda: create_checklist_item(checklist=checklist, actor=member, text="New"),
        "edit": lambda: update_checklist_item(item=item, actor=member, text="Changed"),
        "state": lambda: set_checklist_item_completed(item=item, actor=member, completed=True),
        "delete": lambda: delete_checklist_item(item=item, actor=member),
        "delete_checklist": lambda: delete_checklist(checklist=checklist, actor=member),
    }
    with (
        patch.object(TaskActivity.objects, "create", side_effect=RuntimeError),
        pytest.raises(RuntimeError),
    ):
        actions[operation]()
    assert list(ChecklistItem.objects.values()) == before
    assert TaskChecklist.objects.filter(pk=checklist.pk).exists()
    assert task.activities.count() == 2


def test_checklist_http_lifecycle_and_nested_scope(client, checklist_context):
    context, checklist, item = checklist_context
    _, _, member, task, _ = context
    client.force_login(member.user)
    new = url(context, "checklist_create", task.pk)
    assert client.get(new).status_code == 200
    assert client.post(new, {"title": "Other"}).status_code == 302
    assert client.post(new, {"title": " "}).status_code == 200
    edit = url(context, "checklist_edit", task.pk, checklist.pk)
    assert client.get(edit).status_code == 200
    assert client.post(edit, {"title": "Changed"}).status_code == 302
    create_item = url(context, "checklist_item_create", task.pk, checklist.pk)
    assert client.get(create_item).status_code == 200
    assert client.post(create_item, {"text": "New"}).status_code == 302
    assert client.post(create_item, {"text": " "}).status_code == 200
    edit_item = url(context, "checklist_item_edit", task.pk, checklist.pk, item.pk)
    assert client.get(edit_item).status_code == 200
    assert client.post(edit_item, {"text": "Edited"}).status_code == 302
    state = url(context, "checklist_item_state", task.pk, checklist.pk, item.pk)
    assert client.get(state).status_code == 405
    assert client.post(state, {"completed": "invalid"}).status_code == 302
    assert client.post(state, {"completed": "true"}).status_code == 302
    item.refresh_from_db()
    assert item.is_completed
    other_task = Task.objects.create(column=task.column, title="Foreign", position=1)
    assert (
        client.get(url(context, "checklist_edit", other_task.pk, checklist.pk)).status_code == 404
    )
    other_list = create_checklist(task=task, actor=member, title="Other list")
    assert (
        client.post(
            url(context, "checklist_item_state", task.pk, other_list.pk, item.pk),
            {"completed": "true"},
        ).status_code
        == 404
    )
    assert client.put(url(context, "checklist_edit", 999999, 999999)).status_code == 405
    protected = Client(enforce_csrf_checks=True)
    protected.force_login(member.user)
    assert protected.post(state, {"completed": "true"}).status_code == 403
    delete_item = url(context, "checklist_item_delete", task.pk, checklist.pk, item.pk)
    assert client.get(delete_item).status_code == 200
    assert client.post(delete_item).status_code == 302
    delete = url(context, "checklist_delete", task.pk, checklist.pk)
    assert client.get(delete).status_code == 200
    assert client.post(delete).status_code == 302


def test_archiving_rejects_all_checklist_writes(client, checklist_context):
    context, checklist, item = checklist_context
    board, _, member, task, _ = context
    board.project.status = "archived"
    board.project.save(update_fields=["status"])
    operations = [
        lambda: create_checklist(task=task, actor=member, title="New"),
        lambda: update_checklist(checklist=checklist, actor=member, title="New"),
        lambda: delete_checklist(checklist=checklist, actor=member),
        lambda: create_checklist_item(checklist=checklist, actor=member, text="New"),
        lambda: update_checklist_item(item=item, actor=member, text="New"),
        lambda: set_checklist_item_completed(item=item, actor=member, completed=True),
        lambda: delete_checklist_item(item=item, actor=member),
    ]
    for operation in operations:
        with pytest.raises(ValidationError):
            operation()
    for name, ids, data in [
        ("checklist_create", [task.pk], {"title": "New"}),
        ("checklist_edit", [task.pk, checklist.pk], {"title": "New"}),
        ("checklist_delete", [task.pk, checklist.pk], {}),
        ("checklist_item_create", [task.pk, checklist.pk], {"text": "New"}),
        ("checklist_item_edit", [task.pk, checklist.pk, item.pk], {"text": "New"}),
        ("checklist_item_state", [task.pk, checklist.pk, item.pk], {"completed": "true"}),
        ("checklist_item_delete", [task.pk, checklist.pk, item.pk], {}),
    ]:
        assert client.post(url(context, name, *ids), data).status_code == 302
    assert task.activities.count() == 2


def test_task_cascade_does_not_create_artificial_checklist_events(checklist_context):
    context, _, _ = checklist_context
    task = context[3]
    before = list(task.activities.values_list("pk", flat=True))
    task.delete()
    assert not TaskChecklist.objects.exists()
    assert not ChecklistItem.objects.exists()
    assert list(TaskActivity.objects.values_list("pk", flat=True)) == before
