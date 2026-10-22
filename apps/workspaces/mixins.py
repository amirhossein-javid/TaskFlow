from django.contrib.auth.mixins import LoginRequiredMixin

from .permissions import get_workspace_membership, require_manager, require_owner


class WorkspaceAccessMixin(LoginRequiredMixin):
    """Resolve and cache the current user's workspace membership."""

    workspace = None
    membership = None

    def dispatch(self, request, *args, **kwargs):
        if (
            not request.user.is_authenticated
            or request.method.lower() not in self.http_method_names
        ):
            return super().dispatch(request, *args, **kwargs)
        self.workspace, self.membership = get_workspace_membership(
            user=request.user,
            slug=kwargs["slug"],
        )
        self.check_workspace_permission()
        return super().dispatch(request, *args, **kwargs)

    def check_workspace_permission(self):
        return None

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("workspace", self.workspace)
        context.setdefault("membership", self.membership)
        return context


class WorkspaceOwnerRequiredMixin(WorkspaceAccessMixin):
    def check_workspace_permission(self):
        require_owner(self.membership)


class WorkspaceManagerRequiredMixin(WorkspaceAccessMixin):
    def check_workspace_permission(self):
        require_manager(self.membership)
