import pytest
from django.core.exceptions import PermissionDenied, ValidationError

from apps.accounts.models import User
from apps.projects.models import Project
from apps.projects.services import create_project, set_project_archived, update_project
from apps.workspaces.models import WorkspaceMembership
from apps.workspaces.services import create_workspace

pytestmark = pytest.mark.django_db


def setup_workspace():
    owner = User.objects.create_user(email="owner@example.com", password="SecurePass123!")
    workspace = create_workspace(user=owner, name="Product", slug="product")
    membership = WorkspaceMembership.objects.get(workspace=workspace, user=owner)
    return owner, workspace, membership


def test_manager_can_create_update_archive_and_restore_project():
    owner, workspace, membership = setup_workspace()

    project = create_project(
        workspace=workspace,
        actor=membership,
        name="Launch",
        description="Initial",
    )
    assert project.creator == owner

    project = update_project(
        project=project,
        actor=membership,
        name="Launch v2",
        description="Updated",
    )
    assert project.name == "Launch v2"

    project = set_project_archived(project=project, actor=membership, archived=True)
    assert project.status == Project.Status.ARCHIVED
    project = set_project_archived(project=project, actor=membership, archived=False)
    assert project.status == Project.Status.ACTIVE


def test_member_cannot_manage_projects():
    _, workspace, owner_membership = setup_workspace()
    member_user = User.objects.create_user(email="member@example.com", password="SecurePass123!")
    member = WorkspaceMembership.objects.create(
        workspace=workspace,
        user=member_user,
        role=WorkspaceMembership.Role.MEMBER,
    )
    project = Project.objects.create(
        workspace=workspace, name="Launch", creator=owner_membership.user
    )

    with pytest.raises(PermissionDenied):
        create_project(workspace=workspace, actor=member, name="Denied", description="")
    with pytest.raises(PermissionDenied):
        update_project(project=project, actor=member, name="Denied", description="")
    with pytest.raises(PermissionDenied):
        set_project_archived(project=project, actor=member, archived=True)


def test_cross_workspace_manager_cannot_modify_project():
    owner, workspace, _ = setup_workspace()
    other_owner = User.objects.create_user(email="other@example.com", password="SecurePass123!")
    other_workspace = create_workspace(user=other_owner, name="Other", slug="other")
    other_membership = WorkspaceMembership.objects.get(workspace=other_workspace, user=other_owner)
    project = Project.objects.create(workspace=workspace, name="Launch", creator=owner)

    with pytest.raises(PermissionDenied):
        update_project(
            project=project,
            actor=other_membership,
            name="Compromised",
            description="",
        )


def test_archived_project_cannot_be_updated():
    owner, workspace, membership = setup_workspace()
    project = Project.objects.create(
        workspace=workspace,
        name="Launch",
        creator=owner,
        status=Project.Status.ARCHIVED,
    )

    with pytest.raises(ValidationError, match="بایگانی"):
        update_project(project=project, actor=membership, name="Changed", description="")

    project.refresh_from_db()
    assert project.name == "Launch"
