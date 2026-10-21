from django.core.exceptions import PermissionDenied
from django.shortcuts import get_object_or_404

from .models import Workspace, WorkspaceMembership


def get_workspace_membership(*, user, slug: str) -> tuple[Workspace, WorkspaceMembership]:
    workspace = get_object_or_404(
        Workspace.objects.prefetch_related("memberships__user"),
        slug=slug,
        memberships__user=user,
    )
    membership = get_object_or_404(
        WorkspaceMembership.objects.select_related("user", "workspace"),
        workspace=workspace,
        user=user,
    )
    return workspace, membership


def require_owner(membership: WorkspaceMembership) -> None:
    if membership.role != WorkspaceMembership.Role.OWNER:
        raise PermissionDenied("فقط مالکان فضای کاری به این بخش دسترسی دارند.")


def require_manager(membership: WorkspaceMembership) -> None:
    if membership.role not in [
        WorkspaceMembership.Role.OWNER,
        WorkspaceMembership.Role.ADMIN,
    ]:
        raise PermissionDenied("برای انجام این کار دسترسی کافی ندارید.")
