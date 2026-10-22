import pytest

from apps.accounts.models import User
from apps.boards.models import Task
from apps.boards.services import create_task
from apps.boards.tests.test_concurrency import make_board_context


@pytest.fixture
def context():
    board, actor, member = make_board_context()
    outsider = User.objects.create_user(email="outsider@example.com", password="SecurePass123!")
    return {"board": board, "actor": actor, "member": member, "outsider": outsider}


@pytest.fixture
def assigned_task(context):
    return create_task(
        column=context["board"].columns.first(),
        actor=context["actor"],
        title="Assigned task",
        description="",
        priority=Task.Priority.MEDIUM,
        due_date=None,
        assignee=context["member"].user,
    )
