import pytest
from django.core.exceptions import ValidationError

from apps.boards.models import ChecklistItem
from apps.boards.services import (
    create_checklist,
    create_checklist_item,
    delete_checklist,
    set_checklist_item_completed,
)
from apps.projects.services import set_project_archived

from .test_concurrency import make_board_context, make_task, run_concurrently

pytestmark = pytest.mark.django_db(transaction=True)


def setup_item():
    board, _, member = make_board_context()
    task = make_task(column=board.columns.first(), actor=member, title="Task")
    checklist = create_checklist(task=task, actor=member, title="List")
    item = create_checklist_item(checklist=checklist, actor=member, text="Item")
    return member, task, checklist, item


def test_concurrent_completion_is_idempotent():
    member, task, _, item = setup_item()
    run_concurrently(
        *[
            lambda: set_checklist_item_completed(item=item, actor=member, completed=True)
            for _ in range(2)
        ]
    )
    item.refresh_from_db()
    assert item.is_completed
    assert task.activities.filter(event_type="checklist_item_completed").count() == 1


def test_concurrent_completion_and_checklist_deletion_do_not_resurrect_items():
    member, task, checklist, item = setup_item()

    def complete():
        try:
            set_checklist_item_completed(item=item, actor=member, completed=True)
        except ValidationError:
            pass

    run_concurrently(complete, lambda: delete_checklist(checklist=checklist, actor=member))
    assert not ChecklistItem.objects.filter(pk=item.pk).exists()
    assert task.activities.filter(event_type="checklist_deleted").count() == 1
    assert not task.activities.filter(event_type="checklist_item_deleted").exists()


def test_concurrent_archiving_and_completion_use_locked_project_state():
    board, owner, member = make_board_context()
    task = make_task(column=board.columns.first(), actor=member, title="Task")
    checklist = create_checklist(task=task, actor=member, title="List")
    item = create_checklist_item(checklist=checklist, actor=member, text="Item")

    def complete():
        try:
            set_checklist_item_completed(item=item, actor=member, completed=True)
        except ValidationError:
            pass

    run_concurrently(
        complete, lambda: set_project_archived(project=board.project, actor=owner, archived=True)
    )
    board.project.refresh_from_db()
    item.refresh_from_db()
    assert board.project.status == "archived"
    assert task.activities.filter(event_type="checklist_item_completed").count() == int(
        item.is_completed
    )
