from unittest.mock import patch

import pytest
from django.core.exceptions import PermissionDenied, ValidationError
from django.urls import reverse

from apps.accounts.models import User
from apps.workspaces.models import Workspace, WorkspaceMembership
from apps.workspaces.services import create_workspace, delete_workspace, update_workspace

pytestmark = pytest.mark.django_db


@pytest.mark.parametrize("operation", ["update", "delete"])
@pytest.mark.parametrize("state", ["demoted", "removed", "cross_scope"])
def test_workspace_mutations_reject_stale_or_cross_scope_actors(operation, state):
    user = User.objects.create_user("owner@example.com")
    workspace = create_workspace(user=user, name="Original", slug="original")
    actor = workspace.memberships.get(user=user)
    if state == "removed":
        WorkspaceMembership.objects.filter(pk=actor.pk).delete()
    elif state == "demoted":
        WorkspaceMembership.objects.filter(pk=actor.pk).update(role="member")
    else:
        workspace = create_workspace(user=user, name="Other", slug="other")
    with pytest.raises(PermissionDenied):
        if operation == "update":
            update_workspace(workspace=workspace, actor=actor, name="Changed", slug="changed")
        else:
            delete_workspace(workspace=workspace, actor=actor, confirmation=workspace.name)
    workspace.refresh_from_db()
    assert workspace.slug in {"original", "other"}


def test_delete_rechecks_confirmation_against_current_name():
    user = User.objects.create_user("owner@example.com")
    workspace = create_workspace(user=user, name="Original", slug="original")
    actor = workspace.memberships.get(user=user)
    Workspace.objects.filter(pk=workspace.pk).update(name="Renamed")
    with pytest.raises(ValidationError):
        delete_workspace(workspace=workspace, actor=actor, confirmation="Original")
    assert Workspace.objects.filter(pk=workspace.pk).exists()


@pytest.mark.parametrize("route", ["settings", "delete"])
def test_workspace_views_revalidate_permission_after_dispatch(client, route):
    user = User.objects.create_user("owner@example.com")
    workspace = create_workspace(user=user, name="Original", slug="original")
    client.force_login(user)
    original = WorkspaceMembership.objects.get(user=user)
    from apps.workspaces.views import WorkspaceDeleteView, WorkspaceSettingsView

    view = WorkspaceSettingsView if route == "settings" else WorkspaceDeleteView
    original_form_valid = view.form_valid

    def demote_before_write(self, form):
        WorkspaceMembership.objects.filter(pk=original.pk).update(role="member")
        return original_form_valid(self, form)

    with patch.object(view, "form_valid", demote_before_write):
        response = client.post(
            reverse(f"workspaces:{route}", args=[workspace.slug]),
            {"name": "Changed", "slug": "changed", "confirmation": "Original"},
        )
    assert response.status_code == 403
    workspace.refresh_from_db()
    assert workspace.name == "Original"
