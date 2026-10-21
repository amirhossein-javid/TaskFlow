from .models import WorkspaceMembership


def workspace_navigation(request):
    if not request.user.is_authenticated:
        return {}
    memberships = WorkspaceMembership.objects.filter(user=request.user).select_related("workspace")
    active_slug = request.resolver_match.kwargs.get("slug") if request.resolver_match else None
    return {
        "navigation_memberships": memberships,
        "active_workspace_slug": active_slug,
    }
