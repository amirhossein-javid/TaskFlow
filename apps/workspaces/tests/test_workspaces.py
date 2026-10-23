from datetime import timedelta
from unittest.mock import patch

import pytest
from django.core import mail
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import IntegrityError, transaction
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.workspaces.models import Workspace, WorkspaceInvitation, WorkspaceMembership
from apps.workspaces.services import (
    InvalidInvitation,
    accept_invitation,
    change_membership_role,
    create_invitation,
    create_workspace,
    leave_workspace,
    remove_membership,
)

pytestmark = pytest.mark.django_db


def make_user(email: str) -> User:
    return User.objects.create_user(email=email, password="SecurePass123!")


def make_workspace(owner: User, slug: str = "alpha") -> tuple[Workspace, WorkspaceMembership]:
    workspace = create_workspace(user=owner, name=f"تیم {slug}", slug=slug)
    return workspace, owner.workspace_memberships.get(workspace=workspace)


def add_member(
    workspace: Workspace,
    user: User,
    role: str = WorkspaceMembership.Role.MEMBER,
) -> WorkspaceMembership:
    return WorkspaceMembership.objects.create(workspace=workspace, user=user, role=role)


def test_workspace_creator_becomes_owner():
    user = make_user("owner@example.com")

    workspace, membership = make_workspace(user)

    assert workspace.created_by == user
    assert membership.role == WorkspaceMembership.Role.OWNER


def test_slug_and_membership_are_unique():
    owner = make_user("owner@example.com")
    workspace, _ = make_workspace(owner)

    with pytest.raises(IntegrityError), transaction.atomic():
        Workspace.objects.create(name="Duplicate", slug="ALPHA", created_by=owner)
    with pytest.raises(IntegrityError), transaction.atomic():
        add_member(workspace, owner)


def test_outsider_cannot_view_workspace(client):
    owner = make_user("owner@example.com")
    outsider = make_user("outsider@example.com")
    workspace, _ = make_workspace(owner)
    client.force_login(outsider)

    response = client.get(reverse("workspaces:detail", args=[workspace.slug]))

    assert response.status_code == 404


def test_workspace_list_only_contains_users_workspaces(client):
    user = make_user("member@example.com")
    other = make_user("other@example.com")
    own_workspace, _ = make_workspace(user, "own")
    hidden_workspace, _ = make_workspace(other, "hidden")
    client.force_login(user)

    response = client.get(reverse("workspaces:list"))

    assert own_workspace.name in response.content.decode()
    assert hidden_workspace.name not in response.content.decode()


def test_read_only_workspace_pages_reject_post_and_accept_head(client):
    owner = make_user("owner@example.com")
    workspace, _ = make_workspace(owner)
    client.force_login(owner)
    urls = [
        reverse("workspaces:list"),
        reverse("workspaces:detail", args=[workspace.slug]),
        reverse("workspaces:members", args=[workspace.slug]),
    ]

    for url in urls:
        assert client.head(url).status_code == 200
        assert client.post(url).status_code == 405
        assert client.put(url).status_code == 405
        assert client.options(url).status_code == 405


def test_workspace_form_and_action_views_preserve_original_method_contracts(client):
    owner = make_user("owner@example.com")
    member_user = make_user("member@example.com")
    workspace, owner_membership = make_workspace(owner)
    member = add_member(workspace, member_user)
    _, token = create_invitation(
        workspace=workspace,
        actor=owner_membership,
        email="invitee@example.com",
        role=WorkspaceMembership.Role.MEMBER,
    )
    client.force_login(owner)

    get_post_urls = [
        reverse("workspaces:create"),
        reverse("workspaces:settings", args=[workspace.slug]),
        reverse("workspaces:invite", args=[workspace.slug]),
        reverse("workspaces:remove_member", args=[workspace.slug, member.pk]),
        reverse("workspaces:leave", args=[workspace.slug]),
        reverse("workspaces:delete", args=[workspace.slug]),
        reverse("workspaces:invitation", args=[token]),
    ]
    for url in get_post_urls:
        assert client.get(url).status_code == 200
        assert client.put(url).status_code == 405
        assert client.head(url).status_code == 405
        assert client.options(url).status_code == 405

    post_only_url = reverse("workspaces:change_role", args=[workspace.slug, member.pk])
    assert client.get(post_only_url).status_code == 405
    assert client.put(post_only_url).status_code == 405
    assert client.head(post_only_url).status_code == 405
    assert client.options(post_only_url).status_code == 405


def test_owner_can_promote_member_and_cannot_demote_last_owner():
    owner = make_user("owner@example.com")
    member_user = make_user("member@example.com")
    workspace, owner_membership = make_workspace(owner)
    member = add_member(workspace, member_user)

    change_membership_role(
        actor=owner_membership, target=member, role=WorkspaceMembership.Role.ADMIN
    )
    member.refresh_from_db()
    assert member.role == WorkspaceMembership.Role.ADMIN

    with pytest.raises(ValidationError, match="آخرین مالک"):
        change_membership_role(
            actor=owner_membership,
            target=owner_membership,
            role=WorkspaceMembership.Role.MEMBER,
        )


def test_owner_can_transfer_ownership_safely():
    owner = make_user("owner@example.com")
    successor = make_user("successor@example.com")
    workspace, owner_membership = make_workspace(owner)
    successor_membership = add_member(workspace, successor)

    change_membership_role(
        actor=owner_membership,
        target=successor_membership,
        role=WorkspaceMembership.Role.OWNER,
    )
    change_membership_role(
        actor=owner_membership,
        target=owner_membership,
        role=WorkspaceMembership.Role.MEMBER,
    )

    owner_membership.refresh_from_db()
    successor_membership.refresh_from_db()
    assert owner_membership.role == WorkspaceMembership.Role.MEMBER
    assert successor_membership.role == WorkspaceMembership.Role.OWNER


def test_non_owner_cannot_change_roles():
    owner = make_user("owner@example.com")
    admin_user = make_user("admin@example.com")
    member_user = make_user("member@example.com")
    workspace, _ = make_workspace(owner)
    admin = add_member(workspace, admin_user, WorkspaceMembership.Role.ADMIN)
    member = add_member(workspace, member_user)

    with pytest.raises(PermissionDenied):
        change_membership_role(actor=admin, target=member, role=WorkspaceMembership.Role.ADMIN)


def test_admin_can_remove_member_but_not_owner():
    owner = make_user("owner@example.com")
    admin_user = make_user("admin@example.com")
    member_user = make_user("member@example.com")
    workspace, owner_membership = make_workspace(owner)
    admin = add_member(workspace, admin_user, WorkspaceMembership.Role.ADMIN)
    member = add_member(workspace, member_user)

    remove_membership(actor=admin, target=member)
    assert not WorkspaceMembership.objects.filter(pk=member.pk).exists()
    with pytest.raises(PermissionDenied):
        remove_membership(actor=admin, target=owner_membership)


def test_last_owner_cannot_leave_but_member_can():
    owner = make_user("owner@example.com")
    member_user = make_user("member@example.com")
    workspace, owner_membership = make_workspace(owner)
    member = add_member(workspace, member_user)

    with pytest.raises(ValidationError, match="آخرین مالک"):
        leave_workspace(membership=owner_membership)
    leave_workspace(membership=member)
    assert not WorkspaceMembership.objects.filter(pk=member.pk).exists()


def test_invitation_is_normalized_and_active_invitation_is_unique():
    owner = make_user("owner@example.com")
    workspace, owner_membership = make_workspace(owner)

    invitation, _ = create_invitation(
        workspace=workspace,
        actor=owner_membership,
        email="Person@Example.COM",
        role=WorkspaceMembership.Role.MEMBER,
    )

    assert invitation.email == "person@example.com"
    with pytest.raises(ValidationError, match="دعوت فعال"):
        create_invitation(
            workspace=workspace,
            actor=owner_membership,
            email="person@example.com",
            role=WorkspaceMembership.Role.MEMBER,
        )


def test_admin_may_only_invite_members():
    owner = make_user("owner@example.com")
    admin_user = make_user("admin@example.com")
    workspace, _ = make_workspace(owner)
    admin = add_member(workspace, admin_user, WorkspaceMembership.Role.ADMIN)

    with pytest.raises(PermissionDenied):
        create_invitation(
            workspace=workspace,
            actor=admin,
            email="new@example.com",
            role=WorkspaceMembership.Role.ADMIN,
        )


def test_existing_member_cannot_be_invited():
    owner = make_user("owner@example.com")
    workspace, owner_membership = make_workspace(owner)

    with pytest.raises(ValidationError, match="از قبل عضو"):
        create_invitation(
            workspace=workspace,
            actor=owner_membership,
            email=owner.email,
            role=WorkspaceMembership.Role.MEMBER,
        )


def test_expired_invitation_can_be_replaced():
    owner = make_user("owner@example.com")
    workspace, owner_membership = make_workspace(owner)
    old_invitation, _ = create_invitation(
        workspace=workspace,
        actor=owner_membership,
        email="new@example.com",
        role=WorkspaceMembership.Role.MEMBER,
    )
    WorkspaceInvitation.objects.filter(pk=old_invitation.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    new_invitation, _ = create_invitation(
        workspace=workspace,
        actor=owner_membership,
        email="new@example.com",
        role=WorkspaceMembership.Role.MEMBER,
    )

    old_invitation.refresh_from_db()
    assert old_invitation.revoked_at is not None
    assert new_invitation.pk != old_invitation.pk


def test_invitation_only_accepts_intended_email_and_is_single_use():
    owner = make_user("owner@example.com")
    intended = make_user("intended@example.com")
    wrong_user = make_user("wrong@example.com")
    workspace, owner_membership = make_workspace(owner)
    invitation, token = create_invitation(
        workspace=workspace,
        actor=owner_membership,
        email=intended.email,
        role=WorkspaceMembership.Role.ADMIN,
    )

    with pytest.raises(PermissionDenied):
        accept_invitation(token=token, user=wrong_user)
    membership = accept_invitation(token=token, user=intended)

    assert membership.role == WorkspaceMembership.Role.ADMIN
    invitation.refresh_from_db()
    assert invitation.accepted_by == intended
    with pytest.raises(InvalidInvitation):
        accept_invitation(token=token, user=intended)


def test_expired_invitation_cannot_be_accepted():
    owner = make_user("owner@example.com")
    intended = make_user("intended@example.com")
    workspace, owner_membership = make_workspace(owner)
    invitation, token = create_invitation(
        workspace=workspace,
        actor=owner_membership,
        email=intended.email,
        role=WorkspaceMembership.Role.MEMBER,
    )
    WorkspaceInvitation.objects.filter(pk=invitation.pk).update(
        expires_at=timezone.now() - timedelta(seconds=1)
    )

    with pytest.raises(InvalidInvitation):
        accept_invitation(token=token, user=intended)


def test_invite_view_sends_email_with_acceptance_url(client, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    owner = make_user("owner@example.com")
    workspace, _ = make_workspace(owner)
    client.force_login(owner)

    response = client.post(
        reverse("workspaces:invite", args=[workspace.slug]),
        {"email": "new@example.com", "role": WorkspaceMembership.Role.MEMBER},
    )

    assert response.status_code == 302
    assert len(mail.outbox) == 1
    assert "/workspaces/invitations/" in mail.outbox[0].body


def test_invite_email_failure_preserves_invitation_and_shows_safe_error(client):
    owner = make_user("owner@example.com")
    workspace, _ = make_workspace(owner)
    client.force_login(owner)

    with patch(
        "apps.workspaces.emails.send_mail",
        side_effect=OSError("private SMTP connection details"),
    ):
        response = client.post(
            reverse("workspaces:invite", args=[workspace.slug]),
            {"email": "new@example.com", "role": WorkspaceMembership.Role.MEMBER},
        )

    content = response.content.decode()
    assert response.status_code == 200
    assert WorkspaceInvitation.objects.filter(workspace=workspace, email="new@example.com").exists()
    assert "ارسال دعوت‌نامه تأیید نشد" in content
    assert "دعوت‌نامه با موفقیت ارسال شد" not in content
    assert "private SMTP connection details" not in content


def test_invite_zero_delivery_preserves_invitation(client):
    owner = make_user("owner@example.com")
    workspace, _ = make_workspace(owner)
    client.force_login(owner)

    with patch("apps.workspaces.emails.send_mail", return_value=0):
        response = client.post(
            reverse("workspaces:invite", args=[workspace.slug]),
            {"email": "new@example.com", "role": WorkspaceMembership.Role.MEMBER},
        )

    assert response.status_code == 200
    assert WorkspaceInvitation.objects.filter(workspace=workspace).exists()


def test_member_cannot_open_invitation_form(client):
    owner = make_user("owner@example.com")
    member_user = make_user("member@example.com")
    workspace, _ = make_workspace(owner)
    add_member(workspace, member_user)
    client.force_login(member_user)

    response = client.get(reverse("workspaces:invite", args=[workspace.slug]))

    assert response.status_code == 403


def test_invitation_view_supports_login_and_registration_redirect(client):
    owner = make_user("owner@example.com")
    workspace, owner_membership = make_workspace(owner)
    _, token = create_invitation(
        workspace=workspace,
        actor=owner_membership,
        email="new@example.com",
        role=WorkspaceMembership.Role.MEMBER,
    )
    invitation_path = reverse("workspaces:invitation", args=[token])

    response = client.get(invitation_path)
    content = response.content.decode()
    assert f"{reverse('accounts:login')}?next=" in content
    assert f"{reverse('accounts:register')}?next=" in content

    registration_response = client.post(
        f"{reverse('accounts:register')}?next={invitation_path}",
        {
            "email": "new@example.com",
            "full_name": "کاربر جدید",
            "password1": "SafePassphrase123!",
            "password2": "SafePassphrase123!",
            "next": invitation_path,
        },
    )
    assert registration_response.status_code == 302
    assert registration_response.url == f"{reverse('accounts:login')}?next={invitation_path}"


def test_invitation_post_resolves_token_before_anonymous_login_redirect(client):
    owner = make_user("owner@example.com")
    workspace, owner_membership = make_workspace(owner)
    _, token = create_invitation(
        workspace=workspace,
        actor=owner_membership,
        email="new@example.com",
        role=WorkspaceMembership.Role.MEMBER,
    )

    invalid_response = client.post(reverse("workspaces:invitation", args=["invalid-token"]))
    valid_response = client.post(reverse("workspaces:invitation", args=[token]))

    assert invalid_response.status_code == 404
    assert valid_response.status_code == 302
    assert valid_response.url.startswith(reverse("accounts:login"))


def test_cross_workspace_membership_id_cannot_be_modified(client):
    owner = make_user("owner@example.com")
    other_owner = make_user("other@example.com")
    workspace, _ = make_workspace(owner, "first")
    other_workspace, _ = make_workspace(other_owner, "second")
    foreign_member_user = make_user("foreign@example.com")
    foreign_membership = add_member(other_workspace, foreign_member_user)
    client.force_login(owner)

    response = client.post(
        reverse("workspaces:change_role", args=[workspace.slug, foreign_membership.pk]),
        {"role": WorkspaceMembership.Role.ADMIN},
    )

    assert response.status_code == 404
    foreign_membership.refresh_from_db()
    assert foreign_membership.role == WorkspaceMembership.Role.MEMBER


def test_only_owner_can_delete_workspace_with_exact_confirmation(client):
    owner = make_user("owner@example.com")
    admin_user = make_user("admin@example.com")
    workspace, _ = make_workspace(owner)
    add_member(workspace, admin_user, WorkspaceMembership.Role.ADMIN)

    client.force_login(admin_user)
    assert client.get(reverse("workspaces:delete", args=[workspace.slug])).status_code == 403

    client.force_login(owner)
    url = reverse("workspaces:delete", args=[workspace.slug])
    response = client.post(url, {"confirmation": "نام اشتباه"})
    assert response.status_code == 200
    assert Workspace.objects.filter(pk=workspace.pk).exists()

    response = client.post(url, {"confirmation": workspace.name})
    assert response.status_code == 302
    assert not Workspace.objects.filter(pk=workspace.pk).exists()


def test_workspace_create_detail_members_and_settings_views(client):
    owner = make_user("owner@example.com")
    client.force_login(owner)

    response = client.post(
        reverse("workspaces:create"),
        {"name": "تیم محصول", "slug": "product-team"},
    )
    workspace = Workspace.objects.get(slug="product-team")
    assert response.status_code == 302
    assert workspace.memberships.get(user=owner).role == WorkspaceMembership.Role.OWNER
    assert client.get(reverse("workspaces:detail", args=[workspace.slug])).status_code == 200
    assert client.get(reverse("workspaces:members", args=[workspace.slug])).status_code == 200

    response = client.post(
        reverse("workspaces:settings", args=[workspace.slug]),
        {"name": "تیم محصول جدید", "slug": "new-product-team"},
    )
    workspace.refresh_from_db()
    assert response.status_code == 302
    assert workspace.name == "تیم محصول جدید"
    assert workspace.slug == "new-product-team"


def test_member_cannot_open_settings(client):
    owner = make_user("owner@example.com")
    member_user = make_user("member@example.com")
    workspace, _ = make_workspace(owner)
    add_member(workspace, member_user)
    client.force_login(member_user)

    response = client.get(reverse("workspaces:settings", args=[workspace.slug]))

    assert response.status_code == 403


def test_role_and_remove_views_modify_only_selected_member(client):
    owner = make_user("owner@example.com")
    member_user = make_user("member@example.com")
    workspace, _ = make_workspace(owner)
    member = add_member(workspace, member_user)
    client.force_login(owner)

    role_response = client.post(
        reverse("workspaces:change_role", args=[workspace.slug, member.pk]),
        {"role": WorkspaceMembership.Role.ADMIN},
    )
    member.refresh_from_db()
    assert role_response.status_code == 302
    assert member.role == WorkspaceMembership.Role.ADMIN

    confirm_response = client.get(
        reverse("workspaces:remove_member", args=[workspace.slug, member.pk])
    )
    remove_response = client.post(
        reverse("workspaces:remove_member", args=[workspace.slug, member.pk])
    )
    assert confirm_response.status_code == 200
    assert remove_response.status_code == 302
    assert not WorkspaceMembership.objects.filter(pk=member.pk).exists()


def test_member_can_leave_through_confirmation_view(client):
    owner = make_user("owner@example.com")
    member_user = make_user("member@example.com")
    workspace, _ = make_workspace(owner)
    member = add_member(workspace, member_user)
    client.force_login(member_user)
    url = reverse("workspaces:leave", args=[workspace.slug])

    assert client.get(url).status_code == 200
    response = client.post(url)

    assert response.status_code == 302
    assert not WorkspaceMembership.objects.filter(pk=member.pk).exists()


def test_invitation_view_accepts_once_and_rejects_wrong_account(client):
    owner = make_user("owner@example.com")
    intended = make_user("intended@example.com")
    wrong = make_user("wrong@example.com")
    workspace, owner_membership = make_workspace(owner)
    _, token = create_invitation(
        workspace=workspace,
        actor=owner_membership,
        email=intended.email,
        role=WorkspaceMembership.Role.MEMBER,
    )
    url = reverse("workspaces:invitation", args=[token])

    client.force_login(wrong)
    wrong_response = client.post(url)
    assert wrong_response.status_code == 200
    assert not WorkspaceMembership.objects.filter(workspace=workspace, user=wrong).exists()

    client.force_login(intended)
    accepted_response = client.post(url)
    replay_response = client.post(url)
    assert accepted_response.status_code == 302
    assert replay_response.status_code == 410
    assert WorkspaceMembership.objects.filter(workspace=workspace, user=intended).exists()
