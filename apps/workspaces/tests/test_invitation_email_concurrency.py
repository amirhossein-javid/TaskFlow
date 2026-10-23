import re
from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier, Event
from unittest.mock import patch

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection, transaction
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.workspaces.models import Workspace, WorkspaceInvitation
from apps.workspaces.services import (
    InvalidInvitation,
    accept_invitation,
    change_membership_role,
    create_invitation,
    create_workspace,
    resend_invitation,
)
from apps.workspaces.views import InviteMemberView, ResendInvitationView

pytestmark = pytest.mark.django_db(transaction=True)


def worker(action):
    close_old_connections()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '3s'")
            cursor.execute("SET statement_timeout = '5s'")
        return action()
    finally:
        connection.close()


@pytest.mark.parametrize("resend", [False, True])
def test_concurrency_smtp_begins_after_commit_and_releases_workspace_and_invitation_locks(
    resend, monkeypatch
):
    owner = User.objects.create_user("owner@example.com")
    workspace = create_workspace(user=owner, name="Team", slug="team")
    actor = workspace.memberships.get(user=owner)
    if resend:
        invitation, _ = create_invitation(
            workspace=workspace, actor=actor, email="recipient@example.com", role="member"
        )
        url = reverse("workspaces:resend_invitation", args=[workspace.slug, invitation.pk])
    else:
        url = reverse("workspaces:invite", args=[workspace.slug])
    monkeypatch.setitem(connection.settings_dict, "ATOMIC_REQUESTS", True)
    sending = Barrier(2)
    finish_smtp = Event()
    observation = Queue()

    def smtp(**kwargs):
        with connection.cursor() as cursor:
            cursor.execute("SELECT pg_backend_pid()")
            backend = cursor.fetchone()[0]
        observation.put((connection.in_atomic_block, backend, kwargs["message"]))
        sending.wait(timeout=5)
        assert finish_smtp.wait(timeout=5)
        return 1

    def request():
        client = Client()
        client.force_login(owner)
        response = client.post(url, {"email": "recipient@example.com", "role": "member"})
        return response.status_code, [str(message) for message in response.wsgi_request._messages]

    with (
        patch("apps.workspaces.emails.send_mail", side_effect=smtp),
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        future = executor.submit(worker, request)
        try:
            sending.wait(timeout=5)
            in_atomic, backend, message = observation.get(timeout=5)
            assert not in_atomic
            token = re.search(r"/workspaces/invitations/([^/]+)/", message).group(1)
            # A second connection can see the committed token and acquire every
            # service lock NOWAIT while the original request is still in SMTP.
            with transaction.atomic():
                with connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = '3s'")
                    cursor.execute("SELECT pg_backend_pid()")
                    assert cursor.fetchone()[0] != backend
                locked = Workspace.objects.select_for_update(nowait=True).get(pk=workspace.pk)
                list(locked.memberships.select_for_update(nowait=True).order_by("pk"))
                WorkspaceInvitation.objects.select_for_update(nowait=True).get(
                    token_hash=WorkspaceInvitation.digest_token(token)
                )
                locked.name = "Changed during SMTP"
                locked.save(update_fields=["name"])
        finally:
            finish_smtp.set()
        status, messages = future.result(timeout=10)
        assert status == 302
        assert any("ارسال شد" in message for message in messages)
    workspace.refresh_from_db()
    assert workspace.name == "Changed during SMTP"


def test_concurrency_resends_commit_only_the_latest_hash_without_duplicate_invitations():
    owner = User.objects.create_user("owner@example.com")
    workspace = create_workspace(user=owner, name="Team", slug="team")
    actor = workspace.memberships.get(user=owner)
    invitation, old_token = create_invitation(
        workspace=workspace, actor=actor, email="recipient@example.com", role="member"
    )
    barrier = Barrier(2)

    def rotate():
        barrier.wait(timeout=5)
        _, token = resend_invitation(workspace=workspace, actor=actor, invitation_id=invitation.pk)
        return token

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, rotate) for _ in range(2)]
        tokens = [future.result(timeout=10) for future in futures]
    invitation.refresh_from_db()
    assert len(set(tokens)) == 2
    assert invitation.token_hash in {WorkspaceInvitation.digest_token(token) for token in tokens}
    assert invitation.token_hash != WorkspaceInvitation.digest_token(old_token)
    assert invitation.is_pending and WorkspaceInvitation.objects.count() == 1


def test_concurrency_resend_and_accept_preserve_single_use_through_commit():
    owner = User.objects.create_user("owner@example.com")
    recipient = User.objects.create_user("recipient@example.com")
    workspace = create_workspace(user=owner, name="Team", slug="team")
    actor = workspace.memberships.get(user=owner)
    invitation, token = create_invitation(
        workspace=workspace, actor=actor, email=recipient.email, role="member"
    )
    barrier = Barrier(2)

    def resend():
        barrier.wait(timeout=5)
        try:
            return "resent", resend_invitation(
                workspace=workspace, actor=actor, invitation_id=invitation.pk
            )[1]
        except ValidationError:
            return "closed", None

    def accept():
        barrier.wait(timeout=5)
        try:
            accept_invitation(token=token, user=recipient)
            return "accepted", None
        except InvalidInvitation:
            return "invalid", None

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(worker, action) for action in (resend, accept)]
        resent, accepted = [future.result(timeout=10) for future in futures]
    if resent[0] == "resent":
        assert accepted[0] == "invalid"
        accept_invitation(token=resent[1], user=recipient)
    else:
        assert accepted[0] == "accepted"
    assert workspace.memberships.filter(user=recipient).count() == 1
    invitation.refresh_from_db()
    assert invitation.accepted_by_id == recipient.pk and not invitation.is_pending


@pytest.mark.parametrize("resend", [False, True])
def test_concurrency_invitation_requests_recheck_permission_after_dispatch(resend):
    owner = User.objects.create_user("owner@example.com")
    second = User.objects.create_user("second@example.com")
    workspace = create_workspace(user=owner, name="Team", slug="team")
    actor = workspace.memberships.get(user=owner)
    other = workspace.memberships.create(user=second, role="owner")
    invitation, token = create_invitation(
        workspace=workspace, actor=actor, email="existing@example.com", role="member"
    )
    view = ResendInvitationView if resend else InviteMemberView
    method = "post" if resend else "form_valid"
    original = getattr(view, method)
    dispatched = Barrier(2)

    def after_dispatch(self, *args, **kwargs):
        dispatched.wait(timeout=5)
        return original(self, *args, **kwargs)

    def request():
        client = Client()
        client.force_login(owner)
        url = (
            reverse("workspaces:resend_invitation", args=[workspace.slug, invitation.pk])
            if resend
            else reverse("workspaces:invite", args=[workspace.slug])
        )
        return client.post(url, {"email": "new@example.com", "role": "member"}).status_code

    with (
        patch.object(view, method, after_dispatch),
        patch("apps.workspaces.emails.send_mail") as send,
        ThreadPoolExecutor(max_workers=1) as executor,
    ):
        with transaction.atomic():
            change_membership_role(actor=other, target=actor, role="member")
            future = executor.submit(worker, request)
            dispatched.wait(timeout=5)
        assert future.result(timeout=10) == 403
        send.assert_not_called()
    invitation.refresh_from_db()
    assert invitation.token_hash == WorkspaceInvitation.digest_token(token)
    assert WorkspaceInvitation.objects.count() == 1
