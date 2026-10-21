from django.shortcuts import get_object_or_404

from apps.workspaces.permissions import get_workspace_membership

from .models import Project


def get_project_for_member(*, user, slug: str, project_id: int):
    workspace, membership = get_workspace_membership(user=user, slug=slug)
    project = get_object_or_404(
        Project.objects.select_related("workspace", "creator", "creator__profile"),
        pk=project_id,
        workspace=workspace,
    )
    return workspace, membership, project
