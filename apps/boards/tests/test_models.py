import pytest
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.boards.models import Board, BoardColumn
from apps.boards.signals import DEFAULT_COLUMN_NAMES
from apps.projects.models import Project
from apps.workspaces.services import create_workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def project():
    owner = User.objects.create_user(email="owner@example.com", password="SecurePass123!")
    workspace = create_workspace(user=owner, name="Product", slug="product")
    return Project.objects.create(workspace=workspace, name="Launch", creator=owner)


def test_project_creation_initializes_one_board_with_default_columns(project):
    board = project.board

    assert Board.objects.filter(project=project).count() == 1
    assert list(board.columns.values_list("name", flat=True)) == list(DEFAULT_COLUMN_NAMES)
    assert list(board.columns.values_list("position", flat=True)) == [0, 1, 2]


def test_project_cannot_have_a_second_board(project):
    with pytest.raises(IntegrityError), transaction.atomic():
        Board.objects.create(project=project)


def test_column_positions_are_unique_within_a_board(project):
    with pytest.raises(IntegrityError), transaction.atomic():
        BoardColumn.objects.create(board=project.board, name="Duplicate", position=0)


def test_project_deletion_cascades_to_board_and_columns(project):
    board_id = project.board.pk
    project.delete()

    assert not Board.objects.filter(pk=board_id).exists()
    assert not BoardColumn.objects.filter(board_id=board_id).exists()
