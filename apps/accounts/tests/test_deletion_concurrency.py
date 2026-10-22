from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Event

import pytest
from django.contrib import admin
from django.core.exceptions import PermissionDenied
from django.db import close_old_connections, connection, transaction
from django.test import RequestFactory

from apps.accounts.models import Profile, User
from apps.workspaces.models import WorkspaceInvitation, WorkspaceMembership
from apps.workspaces.services import (
    InvalidInvitation,
    accept_invitation,
    create_invitation,
    create_workspace,
    leave_workspace,
)

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.fixture
def returning_creator():
    creator = User.objects.create_user("creator@example.com")
    owner = User.objects.create_superuser("owner@example.com", "SecurePass123!")
    workspace = create_workspace(user=creator, name="Retained", slug="retained")
    membership = workspace.memberships.get(user=creator)
    owner_membership = workspace.memberships.create(user=owner, role="owner")
    leave_workspace(membership=membership)
    invitation, token = create_invitation(
        workspace=workspace, actor=owner_membership, email=creator.email, role="member"
    )
    return creator, owner, workspace, invitation, token


def run_worker(barrier, action):
    close_old_connections()
    try:
        with connection.cursor() as cursor:
            cursor.execute("SET lock_timeout = '5s'")
            cursor.execute("SET statement_timeout = '10s'")
            cursor.execute("SELECT pg_backend_pid()")
            backend_id = cursor.fetchone()[0]
        barrier.wait(timeout=5)
        try:
            with transaction.atomic():
                result = action()
        except PermissionDenied:
            result = "forbidden"
        except InvalidInvitation:
            result = "invalid"
        return backend_id, result
    finally:
        connection.close()


@pytest.mark.parametrize("bulk", [False, True])
@pytest.mark.parametrize("winner", ["deletion", "acceptance"])
def test_concurrency_user_deletion_and_invitation_acceptance_commit_safely(
    returning_creator, bulk, winner
):
    creator, owner, workspace, invitation, token = returning_creator
    creator_id = creator.pk
    barrier = Barrier(2)
    membership_checked = Event()
    acceptance_attempted = Event()
    acceptance_written = Event()
    deletion_attempted = Event()
    user_admin = admin.site._registry[User]
    request = RequestFactory().post("/admin/accounts/user/")
    request.user = owner

    def observe_deletion(execute, sql, params, many, context):
        if 'FROM "accounts_user"' in sql and "FOR UPDATE" in sql:
            deletion_attempted.set()
        result = execute(sql, params, many, context)
        if winner == "deletion" and 'FROM "workspaces_workspacemembership"' in sql:
            membership_checked.set()
            assert acceptance_attempted.wait(timeout=5)
        return result

    def observe_acceptance(execute, sql, params, many, context):
        if 'FROM "accounts_user"' in sql and "FOR NO KEY UPDATE" in sql:
            acceptance_attempted.set()
        result = execute(sql, params, many, context)
        # With the original workspace-first code this releases deletion only
        # after acceptance owns the workspace, exposing the FK cycle at commit.
        if 'FROM "workspaces_workspace"' in sql and "FOR UPDATE" in sql:
            acceptance_attempted.set()
        return result

    def delete():
        if winner == "acceptance":
            assert acceptance_written.wait(timeout=5)
        with connection.execute_wrapper(observe_deletion):
            if bulk:
                user_admin.delete_queryset(request, User.objects.filter(pk=creator_id))
            else:
                user_admin.delete_model(request, creator)
        return "deleted"

    def accept():
        if winner == "deletion":
            assert membership_checked.wait(timeout=5)
        with connection.execute_wrapper(observe_acceptance):
            accept_invitation(token=token, user=creator)
        acceptance_written.set()
        if winner == "acceptance":
            assert deletion_attempted.wait(timeout=5)
        return "accepted"

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = [executor.submit(run_worker, barrier, action) for action in (delete, accept)]
        results = [future.result(timeout=20) for future in futures]
    assert results[0][0] != results[1][0]
    workspace.refresh_from_db()
    invitation.refresh_from_db()
    assert workspace.memberships.filter(user=owner, role="owner").count() == 1
    if winner == "deletion":
        assert [result for _, result in results] == ["deleted", "invalid"]
        assert not User.objects.filter(pk=creator_id).exists()
        assert not Profile.objects.filter(user_id=creator_id).exists()
        assert workspace.created_by_id is None
        assert invitation.accepted_at is None
        assert invitation.accepted_by_id is None
    else:
        assert [result for _, result in results] == ["forbidden", "accepted"]
        assert User.objects.filter(pk=creator_id).exists()
        assert Profile.objects.filter(user_id=creator_id).exists()
        assert workspace.created_by_id == creator_id
        assert workspace.memberships.filter(user_id=creator_id, role="member").exists()
        assert invitation.accepted_at is not None
        assert invitation.accepted_by_id == creator_id


def test_concurrency_accepting_user_lock_allows_other_invitation_fk_commit(returning_creator):
    creator, _, _, _, token = returning_creator
    other_workspace = create_workspace(user=creator, name="Other", slug="other")
    actor = other_workspace.memberships.get(user=creator)
    barrier = Barrier(2)
    user_locked = Event()
    other_committed = Event()

    def observe_user_lock(execute, sql, params, many, context):
        result = execute(sql, params, many, context)
        if 'FROM "accounts_user"' in sql and "FOR NO KEY UPDATE" in sql:
            user_locked.set()
            assert other_committed.wait(timeout=5)
        return result

    def accept():
        with connection.execute_wrapper(observe_user_lock):
            accept_invitation(token=token, user=creator)
        return "accepted"

    def invite():
        assert user_locked.wait(timeout=5)
        # The worker commits while acceptance still holds its User lock. The
        # invitation's deferred invited_by FK needs KEY SHARE on that User.
        create_invitation(
            workspace=other_workspace, actor=actor, email="new@example.com", role="member"
        )
        return "invited"

    def invite_and_signal():
        # run_worker commits its outer transaction before the signal is sent.
        result = run_worker(barrier, invite)
        other_committed.set()
        return result

    with ThreadPoolExecutor(max_workers=2) as executor:
        accepted = executor.submit(run_worker, barrier, accept)
        invited = executor.submit(invite_and_signal)
        assert accepted.result(timeout=20)[1] == "accepted"
        assert invited.result(timeout=20)[1] == "invited"
    assert WorkspaceInvitation.objects.filter(
        workspace=other_workspace, invited_by=creator
    ).exists()
    assert WorkspaceMembership.objects.filter(workspace__slug="retained", user=creator).exists()


def test_concurrency_forbidden_bulk_delete_does_not_wait_on_another_accepting_user(
    returning_creator,
):
    _, owner, workspace, _, _ = returning_creator
    later_user = User.objects.create_user("later@example.com")
    assert owner.pk < later_user.pk
    _, token = create_invitation(
        workspace=workspace,
        actor=workspace.memberships.get(user=owner),
        email=later_user.email,
        role="member",
    )
    barrier = Barrier(2)
    request = RequestFactory().post("/admin/accounts/user/")
    request.user = owner

    def delete():
        admin.site._registry[User].delete_queryset(
            request, User.objects.filter(pk__in=[owner.pk, later_user.pk])
        )

    with ThreadPoolExecutor(max_workers=1) as executor:
        with transaction.atomic():
            accept_invitation(token=token, user=later_user)
            future = executor.submit(run_worker, barrier, delete)
            barrier.wait(timeout=5)
            # Reject at the first member before waiting for another User lock.
            # Holding the owner's User lock while waiting could block the
            # committing FK checks of a workspace writer acceptance waits on.
            assert future.result(timeout=15)[1] == "forbidden"
    assert User.objects.filter(pk__in=[owner.pk, later_user.pk]).count() == 2
    assert workspace.memberships.filter(user=owner, role="owner").exists()
    assert workspace.memberships.filter(user=later_user).exists()
