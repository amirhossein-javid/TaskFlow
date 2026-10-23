import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.projects.models import Project
from apps.workspaces.models import WorkspaceInvitation, WorkspaceMembership
from apps.workspaces.services import create_invitation, create_workspace

pytestmark = pytest.mark.django_db


@pytest.fixture
def domain_admin(client):
    user = User.objects.create_superuser("admin@example.com", "SecurePass123!")
    workspace = create_workspace(user=user, name="Protected", slug="protected")
    membership = workspace.memberships.get(user=user)
    project = Project.objects.create(workspace=workspace, name="Protected project")
    invitation, _ = create_invitation(
        workspace=workspace, actor=membership, email="invited@example.com", role="member"
    )
    client.force_login(user)
    return user, workspace, membership, project, invitation


@pytest.mark.parametrize("index", [1, 3, 4])
def test_domain_admin_rejects_all_direct_writes(client, domain_admin, index):
    instance = domain_admin[index]
    model = type(instance)
    prefix = f"admin:{model._meta.app_label}_{model._meta.model_name}"
    original = model.objects.values().get(pk=instance.pk)
    assert client.get(reverse(f"{prefix}_change", args=[instance.pk])).status_code == 200
    assert client.post(reverse(f"{prefix}_change", args=[instance.pk]), {}).status_code == 403
    assert client.get(reverse(f"{prefix}_add")).status_code == 403
    assert (
        client.post(reverse(f"{prefix}_delete", args=[instance.pk]), {"post": "yes"}).status_code
        == 403
    )
    client.post(
        reverse(f"{prefix}_changelist"),
        {"action": "delete_selected", "_selected_action": [instance.pk], "post": "yes"},
    )
    assert model.objects.values().get(pk=instance.pk) == original


def test_membership_inline_cannot_remove_or_demote_last_owner(client, domain_admin):
    _, workspace, membership, _, _ = domain_admin
    response = client.get(reverse("admin:workspaces_workspace_change", args=[workspace.pk]))
    inline = response.context["inline_admin_formsets"][0]
    assert not inline.has_add_permission
    assert not inline.has_change_permission
    assert not inline.has_delete_permission
    response = client.post(
        reverse("admin:workspaces_workspace_change", args=[workspace.pk]),
        {
            "memberships-0-id": membership.pk,
            "memberships-0-role": "member",
            "memberships-0-DELETE": "on",
        },
    )
    assert response.status_code == 403
    assert WorkspaceMembership.objects.get(pk=membership.pk).role == "owner"


@pytest.mark.parametrize("bulk", [False, True])
def test_admin_cannot_delete_users_with_memberships(client, domain_admin, bulk):
    user, workspace, _, _, _ = domain_admin
    other = User.objects.create_user("other@example.com")
    if bulk:
        response = client.post(
            reverse("admin:accounts_user_changelist"),
            {"action": "delete_selected", "_selected_action": [user.pk, other.pk], "post": "yes"},
        )
    else:
        response = client.post(
            reverse("admin:accounts_user_delete", args=[user.pk]), {"post": "yes"}
        )
    assert response.status_code == 403
    assert User.objects.filter(pk__in=[user.pk, other.pk]).count() == 2
    assert workspace.memberships.filter(role="owner").count() == 1
    assert WorkspaceInvitation.objects.filter(workspace=workspace).exists()
