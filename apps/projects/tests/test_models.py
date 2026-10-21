import pytest
from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction

from apps.accounts.models import User
from apps.projects.models import Project
from apps.workspaces.services import create_workspace

pytestmark = pytest.mark.django_db


def test_project_belongs_to_workspace_and_defaults_to_active():
    owner = User.objects.create_user(email="owner@example.com", password="SecurePass123!")
    workspace = create_workspace(user=owner, name="Product", slug="product")

    project = Project.objects.create(workspace=workspace, name="Launch", creator=owner)

    assert project.status == Project.Status.ACTIVE
    assert project.description == ""
    assert project in workspace.projects.all()


def test_workspace_deletion_cascades_to_projects():
    owner = User.objects.create_user(email="owner@example.com", password="SecurePass123!")
    workspace = create_workspace(user=owner, name="Product", slug="product")
    project = Project.objects.create(workspace=workspace, name="Launch", creator=owner)

    workspace.delete()

    assert not Project.objects.filter(pk=project.pk).exists()


def test_creator_deletion_preserves_project():
    owner = User.objects.create_user(email="owner@example.com", password="SecurePass123!")
    workspace = create_workspace(user=owner, name="Product", slug="product")
    project = Project.objects.create(workspace=workspace, name="Launch", creator=owner)

    owner.delete()

    project.refresh_from_db()
    assert project.creator is None


def test_project_rejects_blank_name_during_validation():
    owner = User.objects.create_user(email="owner@example.com", password="SecurePass123!")
    workspace = create_workspace(user=owner, name="Product", slug="product")
    project = Project(workspace=workspace, name="   ", creator=owner)

    with pytest.raises(ValidationError, match="نام پروژه"):
        project.full_clean()


def test_database_rejects_invalid_status():
    owner = User.objects.create_user(email="owner@example.com", password="SecurePass123!")
    workspace = create_workspace(user=owner, name="Product", slug="product")

    with pytest.raises(IntegrityError), transaction.atomic():
        Project.objects.create(
            workspace=workspace,
            name="Launch",
            creator=owner,
            status="invalid",
        )
