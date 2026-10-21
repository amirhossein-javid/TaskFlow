from django.shortcuts import get_object_or_404

from apps.workspaces.mixins import WorkspaceAccessMixin
from apps.workspaces.permissions import require_manager

from .models import Project


class ProjectAccessMixin(WorkspaceAccessMixin):
    """Resolve a project inside the current member's workspace."""

    project = None

    def check_workspace_permission(self):
        super().check_workspace_permission()
        self.project = get_object_or_404(
            Project.objects.select_related("workspace", "creator", "creator__profile"),
            pk=self.kwargs["project_id"],
            workspace=self.workspace,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("project", self.project)
        return context


class ProjectManagerRequiredMixin(ProjectAccessMixin):
    def check_workspace_permission(self):
        super().check_workspace_permission()
        require_manager(self.membership)
