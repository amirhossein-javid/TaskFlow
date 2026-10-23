import re
import smtplib
from datetime import timedelta
from unittest.mock import patch

import pytest
from django.contrib.messages import get_messages
from django.core import mail
from django.core.exceptions import PermissionDenied
from django.test import Client
from django.urls import reverse
from django.utils import timezone

from apps.accounts.models import User
from apps.workspaces.models import WorkspaceInvitation, WorkspaceMembership
from apps.workspaces.services import (
    InvalidInvitation,
    accept_invitation,
    create_invitation,
    create_workspace,
    resend_invitation,
)

pytestmark = pytest.mark.django_db


@pytest.fixture
def invitation_state(client, settings):
    settings.EMAIL_BACKEND = "django.core.mail.backends.locmem.EmailBackend"
    owner = User.objects.create_user("owner@example.com")
    workspace = create_workspace(user=owner, name="Team", slug="team")
    actor = workspace.memberships.get(user=owner)
    invitation, token = create_invitation(
        workspace=workspace,
        actor=actor,
        email="recipient@example.com",
        role="member",
    )
    client.force_login(owner)
    return workspace, actor, invitation, token


def resend_url(workspace, invitation):
    return reverse("workspaces:resend_invitation", args=[workspace.slug, invitation.pk])


def email_token():
    return re.search(r"/workspaces/invitations/([^/]+)/", mail.outbox[-1].body).group(1)


def test_resend_rotates_hash_preserves_identity_and_expiry_and_accepts_only_new_link(
    client, invitation_state
):
    workspace, actor, invitation, old_token = invitation_state
    previous = (
        invitation.expires_at,
        invitation.created_at,
        invitation.invited_by_id,
        invitation.role,
        invitation.email,
    )
    response = client.post(resend_url(workspace, invitation))
    assert response.status_code == 302
    assert response.url == reverse("workspaces:members", args=[workspace.slug])
    token = email_token()
    assert token != old_token
    assert client.get(reverse("workspaces:invitation", args=[old_token])).status_code == 404
    assert client.get(reverse("workspaces:invitation", args=[token])).status_code == 200
    invitation.refresh_from_db()
    assert invitation.token_hash == WorkspaceInvitation.digest_token(token)
    assert token not in vars(invitation).values()
    assert previous == (
        invitation.expires_at,
        invitation.created_at,
        invitation.invited_by_id,
        invitation.role,
        invitation.email,
    )
    assert WorkspaceInvitation.objects.count() == 1
    recipient = User.objects.create_user(invitation.email)
    with pytest.raises(InvalidInvitation):
        accept_invitation(token=old_token, user=recipient)
    assert accept_invitation(token=token, user=recipient).role == "member"
    with pytest.raises(InvalidInvitation):
        accept_invitation(token=token, user=recipient)


@pytest.mark.parametrize(
    "outcome",
    [0, TimeoutError("private SMTP response"), smtplib.SMTPDataError(451, b"private response")],
)
def test_unconfirmed_resend_keeps_new_hash_and_can_retry_without_reviving_old_token(
    client, invitation_state, outcome, caplog
):
    workspace, actor, invitation, old_token = invitation_state

    def send(**kwargs):
        # Simulate SMTP accepting DATA before a lost reply: the new URL already exists.
        assert kwargs["fail_silently"] is False
        token = re.search(r"/workspaces/invitations/([^/]+)/", kwargs["message"]).group(1)
        assert WorkspaceInvitation.objects.get(
            pk=invitation.pk
        ).token_hash == WorkspaceInvitation.digest_token(token)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    with patch("apps.workspaces.emails.send_mail", side_effect=send):
        response = client.post(resend_url(workspace, invitation))
    assert response.status_code == 302
    feedback = list(get_messages(response.wsgi_request))
    assert all(message.level_tag != "success" for message in feedback)
    assert "ممکن است ایمیل ارسال شده باشد" in str(feedback[0])
    assert "پیوند قبلی دیگر معتبر نیست" in str(feedback[0])
    assert "private" not in caplog.text
    assert invitation.email not in caplog.text and old_token not in caplog.text
    invitation.refresh_from_db()
    failed_hash = invitation.token_hash
    assert invitation.is_pending and failed_hash != WorkspaceInvitation.digest_token(old_token)
    assert client.post(resend_url(workspace, invitation)).status_code == 302
    invitation.refresh_from_db()
    assert invitation.token_hash != failed_hash
    assert invitation.token_hash == WorkspaceInvitation.digest_token(email_token())


@pytest.mark.parametrize("state", ["expired", "revoked", "accepted", "already_member"])
def test_resend_rejects_non_pending_or_existing_members_without_sending(
    client, invitation_state, state
):
    workspace, actor, invitation, token = invitation_state
    if state == "expired":
        invitation.expires_at = timezone.now() - timedelta(seconds=1)
    elif state == "revoked":
        invitation.revoked_at = timezone.now()
    elif state == "accepted":
        invitation.accepted_at = timezone.now()
    else:
        workspace.memberships.create(user=User.objects.create_user(invitation.email), role="member")
    invitation.save()
    response = client.post(resend_url(workspace, invitation))
    assert response.status_code == 302
    assert not mail.outbox
    invitation.refresh_from_db()
    assert invitation.token_hash == WorkspaceInvitation.digest_token(token)


@pytest.mark.parametrize(
    "role,invited_role,status",
    [
        ("owner", "admin", 302),
        ("admin", "member", 302),
        ("admin", "admin", 403),
        ("member", "member", 403),
    ],
)
def test_resend_permissions_match_invitation_creation(
    client, invitation_state, role, invited_role, status
):
    workspace, actor, invitation, token = invitation_state
    if role != "owner":
        manager = User.objects.create_user("manager@example.com")
        workspace.memberships.create(user=manager, role=role)
        client.force_login(manager)
    invitation.role = invited_role
    invitation.save(update_fields=["role"])
    url = resend_url(workspace, invitation)
    members = client.get(reverse("workspaces:members", args=[workspace.slug])).content.decode()
    assert (f'action="{url}"' in members) == (status == 302)
    assert client.post(url).status_code == status
    assert len(mail.outbox) == (1 if status == 302 else 0)


def test_resend_scopes_target_and_requires_authentication_post_and_csrf(client, invitation_state):
    workspace, actor, invitation, token = invitation_state
    other = create_workspace(user=actor.user, name="Other", slug="other")
    assert (
        client.post(
            reverse("workspaces:resend_invitation", args=[other.slug, invitation.pk])
        ).status_code
        == 404
    )
    assert (
        client.post(
            reverse("workspaces:resend_invitation", args=[workspace.slug, 999999])
        ).status_code
        == 404
    )
    outsider = User.objects.create_user("outsider@example.com")
    client.force_login(outsider)
    assert client.post(resend_url(workspace, invitation)).status_code == 404
    for method in ("get", "head", "put", "delete", "options"):
        response = getattr(client, method)(
            reverse("workspaces:resend_invitation", args=["missing", 999999])
        )
        assert response.status_code == 405 and response.headers["Allow"] == "POST"
    client.logout()
    assert client.post(resend_url(workspace, invitation)).status_code == 302
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(actor.user)
    assert csrf_client.post(resend_url(workspace, invitation)).status_code == 403
    assert not mail.outbox
    invitation.refresh_from_db()
    assert invitation.token_hash == WorkspaceInvitation.digest_token(token)


@pytest.mark.parametrize("removed", [False, True])
def test_resend_service_revalidates_actor_membership(invitation_state, removed):
    workspace, actor, invitation, token = invitation_state
    if removed:
        WorkspaceMembership.objects.filter(pk=actor.pk).delete()
    else:
        WorkspaceMembership.objects.filter(pk=actor.pk).update(role="member")
    with pytest.raises(PermissionDenied):
        resend_invitation(workspace=workspace, actor=actor, invitation_id=invitation.pk)
    invitation.refresh_from_db()
    assert invitation.token_hash == WorkspaceInvitation.digest_token(token)
