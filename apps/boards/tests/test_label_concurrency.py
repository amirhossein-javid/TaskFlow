import pytest
from django.core.exceptions import ValidationError

from apps.boards.models import ProjectLabel, TaskLabel
from apps.boards.services import create_project_label, delete_project_label, set_task_label

from .test_concurrency import make_board_context, make_task, run_concurrently

pytestmark = pytest.mark.django_db(transaction=True)


def test_concurrent_label_creation_enforces_project_uniqueness():
    board, owner, _ = make_board_context()

    def create(name):
        try:
            create_project_label(board=board, actor=owner, name=name, color="blue")
        except ValidationError:
            pass

    run_concurrently(lambda: create("Bug"), lambda: create("bug"))
    assert ProjectLabel.objects.filter(project=board.project).count() == 1


def test_concurrent_label_attachment_records_one_event():
    board, owner, member = make_board_context()
    task = make_task(column=board.columns.first(), actor=member, title="Task")
    label = create_project_label(board=board, actor=owner, name="Bug", color="red")
    run_concurrently(
        *[
            lambda: set_task_label(task=task, label=label, actor=member, attached=True)
            for _ in range(2)
        ]
    )
    assert TaskLabel.objects.filter(task=task, label=label).count() == 1
    assert task.activities.filter(event_type="label_attached").count() == 1


def test_concurrent_label_deletion_and_attachment_do_not_leave_links():
    board, owner, member = make_board_context()
    task = make_task(column=board.columns.first(), actor=member, title="Task")
    label = create_project_label(board=board, actor=owner, name="Bug", color="red")

    def attach():
        try:
            set_task_label(task=task, label=label, actor=member, attached=True)
        except ValidationError:
            pass

    run_concurrently(attach, lambda: delete_project_label(label=label, actor=owner))
    assert not ProjectLabel.objects.filter(pk=label.pk).exists()
    assert not task.labels.exists()
    assert task.activities.filter(event_type="label_attached").count() <= 1
    assert not task.activities.filter(event_type="label_detached").exists()
