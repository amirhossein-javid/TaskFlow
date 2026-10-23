import re
import smtplib
import socketserver
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from email import policy
from email.parser import BytesParser
from queue import Queue
from threading import Event
from time import monotonic
from unittest.mock import patch

import pytest
from django.test import override_settings
from django.urls import reverse

from apps.accounts.models import User
from apps.workspaces.models import WorkspaceInvitation
from apps.workspaces.services import accept_invitation, create_workspace

pytestmark = pytest.mark.django_db


@contextmanager
def smtp_server(outcome):
    """A bounded local SMTP peer that can stall after receiving DATA."""
    received = Queue()
    stop = Event()

    class Handler(socketserver.StreamRequestHandler):
        def handle(self):
            self.request.settimeout(2)
            try:
                self.wfile.write(b"220 localhost\r\n")
                while line := self.rfile.readline():
                    command = line.split()[0].upper()
                    if command == b"DATA":
                        self.wfile.write(b"354 send data\r\n")
                        message = b""
                        while (line := self.rfile.readline()) not in {b".\r\n", b""}:
                            message += line
                        received.put(message)
                        if outcome == "timeout":
                            stop.wait(timeout=2)
                            return
                        self.wfile.write(
                            b"250 accepted\r\n" if outcome == "success" else b"451 unavailable\r\n"
                        )
                    elif command == b"QUIT":
                        self.wfile.write(b"221 goodbye\r\n")
                        return
                    else:
                        self.wfile.write(b"250 OK\r\n")
            except OSError:
                pass

    class Server(socketserver.ThreadingTCPServer):
        daemon_threads = True

    with Server(("127.0.0.1", 0), Handler) as server, ThreadPoolExecutor(max_workers=1) as executor:
        future = executor.submit(server.serve_forever, poll_interval=0.02)
        try:
            with override_settings(
                EMAIL_BACKEND="django.core.mail.backends.smtp.EmailBackend",
                EMAIL_HOST="127.0.0.1",
                EMAIL_PORT=server.server_address[1],
                EMAIL_USE_TLS=False,
                EMAIL_USE_SSL=False,
                EMAIL_HOST_USER="",
                EMAIL_HOST_PASSWORD="",
                EMAIL_TIMEOUT=0.15,
            ):
                yield received
        finally:
            stop.set()
            server.shutdown()
            future.result(timeout=3)


@pytest.mark.parametrize("outcome,status", [("success", 302), ("reject", 200), ("timeout", 200)])
def test_invitation_uses_smtp_timeout_and_preserves_committed_token_after_data(
    client, outcome, status
):
    owner = User.objects.create_user("owner@example.com")
    workspace = create_workspace(user=owner, name="Team", slug="team")
    client.force_login(owner)
    with smtp_server(outcome) as received:
        started = monotonic()
        response = client.post(
            reverse("workspaces:invite", args=[workspace.slug]),
            {"email": "recipient@example.com", "role": "member"},
        )
        assert monotonic() - started < 2
        assert response.status_code == status
        message = received.get(timeout=1)
        assert b"recipient@example.com" in message
    invitation = WorkspaceInvitation.objects.get(workspace=workspace)
    assert invitation.is_pending
    content = BytesParser(policy=policy.default).parsebytes(message).get_content()
    token = re.search(r"/workspaces/invitations/([^/]+)/", content).group(1)
    assert invitation.token_hash == WorkspaceInvitation.digest_token(token)
    recipient = User.objects.create_user(invitation.email)
    assert accept_invitation(token=token, user=recipient).workspace_id == workspace.pk
    if outcome != "success":
        assert "ارسال دعوت‌نامه تأیید نشد" in response.content.decode()


@pytest.mark.parametrize("outcome", ["success", "reject", "timeout"])
def test_password_reset_smtp_outcomes_do_not_disclose_account_existence(client, outcome):
    User.objects.create_user("known@example.com", "StrongPass!2026")
    inactive = User.objects.create_user("inactive@example.com", "StrongPass!2026", is_active=False)
    unusable = User.objects.create_user("unusable@example.com")
    with smtp_server(outcome) as received:
        responses = [
            client.post(reverse("accounts:password_reset"), {"email": email})
            for email in (
                "known@example.com",
                "unknown@example.com",
                inactive.email,
                unusable.email,
            )
        ]
        assert all(response.status_code == 302 for response in responses)
        assert {response.url for response in responses} == {reverse("accounts:password_reset_done")}
        assert b"known@example.com" in received.get(timeout=1)
        assert received.empty()
        content = client.get(responses[0].url).content.decode()
        assert "known@example.com" not in content and "ارسال شده است" not in content


def test_password_reset_connection_failure_keeps_generic_redirect(client):
    User.objects.create_user("known@example.com", "StrongPass!2026")
    with patch(
        "django.core.mail.message.EmailMultiAlternatives.send",
        side_effect=smtplib.SMTPConnectError(421, b"private connection details"),
    ):
        response = client.post(reverse("accounts:password_reset"), {"email": "known@example.com"})
    assert response.status_code == 302
    assert response.url == reverse("accounts:password_reset_done")
    assert "private" not in client.get(response.url).content.decode()
