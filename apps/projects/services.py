from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction

from apps.workspaces.models import Workspace, WorkspaceMembership

from .models import Project


def _locked_manager(*, membership_id: int, workspace_id: int) -> WorkspaceMembership:
    membership = (
        WorkspaceMembership.objects.select_for_update()
        .filter(pk=membership_id, workspace_id=workspace_id)
        .first()
    )
    if not membership or membership.role not in [
        WorkspaceMembership.Role.OWNER,
        WorkspaceMembership.Role.ADMIN,
    ]:
        raise PermissionDenied
    return membership


@transaction.atomic
def create_project(
    *, workspace: Workspace, actor: WorkspaceMembership, name: str, description: str
) -> Project:
    Workspace.objects.select_for_update().get(pk=workspace.pk)
    actor = _locked_manager(membership_id=actor.pk, workspace_id=workspace.pk)
    return Project.objects.create(
        workspace=workspace,
        name=name,
        description=description,
        creator=actor.user,
    )


@transaction.atomic
def update_project(
    *, project: Project, actor: WorkspaceMembership, name: str, description: str
) -> Project:
    project = Project.objects.select_for_update().get(pk=project.pk)
    _locked_manager(membership_id=actor.pk, workspace_id=project.workspace_id)
    if project.status == Project.Status.ARCHIVED:
        raise ValidationError("پروژهٔ بایگانی‌شده تا زمان بازیابی قابل ویرایش نیست.")
    project.name = name
    project.description = description
    project.save(update_fields=["name", "description", "updated_at"])
    return project


@transaction.atomic
def set_project_archived(
    *, project: Project, actor: WorkspaceMembership, archived: bool
) -> Project:
    project = Project.objects.select_for_update().get(pk=project.pk)
    _locked_manager(membership_id=actor.pk, workspace_id=project.workspace_id)
    project.status = Project.Status.ARCHIVED if archived else Project.Status.ACTIVE
    project.save(update_fields=["status", "updated_at"])
    return project
