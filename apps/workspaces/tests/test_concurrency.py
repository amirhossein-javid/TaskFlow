from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

import pytest
from django.core.exceptions import ValidationError
from django.db import close_old_connections, connection

from apps.accounts.models import User
from apps.workspaces.models import WorkspaceMembership
from apps.workspaces.services import (
    change_membership_role,
    create_workspace,
    leave_workspace,
    remove_membership,
)

pytestmark = pytest.mark.django_db(transaction=True)


def make_two_owner_workspace():
    first_user = User.objects.create_user(
        email="first-owner@example.com", password="SecurePass123!"
    )
    second_user = User.objects.create_user(
        email="second-owner@example.com", password="SecurePass123!"
    )
    workspace = create_workspace(user=first_user, name="Concurrent", slug="concurrent")
    first = WorkspaceMembership.objects.get(workspace=workspace, user=first_user)
    second = WorkspaceMembership.objects.create(
        workspace=workspace,
        user=second_user,
        role=WorkspaceMembership.Role.OWNER,
    )
    return workspace, first, second


def run_concurrently(*actions):
    barrier = Barrier(len(actions))

    def run(action):
        close_old_connections()
        try:
            barrier.wait(timeout=5)
            action()
        except ValidationError:
            return "rejected"
        finally:
            connection.close()
        return "completed"

    with ThreadPoolExecutor(max_workers=len(actions)) as executor:
        futures = [executor.submit(run, action) for action in actions]
        return [future.result(timeout=10) for future in futures]


def assert_one_owner_remains(workspace):
    assert (
        WorkspaceMembership.objects.filter(
            workspace=workspace,
            role=WorkspaceMembership.Role.OWNER,
        ).count()
        == 1
    )


def test_concurrent_owner_demotions_preserve_one_owner():
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency is PostgreSQL-specific.")
    workspace, first, second = make_two_owner_workspace()

    results = run_concurrently(
        lambda: change_membership_role(
            actor=first, target=first, role=WorkspaceMembership.Role.MEMBER
        ),
        lambda: change_membership_role(
            actor=second, target=second, role=WorkspaceMembership.Role.MEMBER
        ),
    )

    assert sorted(results) == ["completed", "rejected"]
    assert_one_owner_remains(workspace)


def test_concurrent_owner_removals_preserve_one_owner():
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency is PostgreSQL-specific.")
    workspace, first, second = make_two_owner_workspace()

    results = run_concurrently(
        lambda: remove_membership(actor=first, target=second),
        lambda: remove_membership(actor=second, target=first),
    )

    assert sorted(results) == ["completed", "rejected"]
    assert_one_owner_remains(workspace)


def test_concurrent_owner_departures_preserve_one_owner():
    if connection.vendor != "postgresql":
        pytest.skip("Row-lock concurrency is PostgreSQL-specific.")
    workspace, first, second = make_two_owner_workspace()

    results = run_concurrently(
        lambda: leave_workspace(membership=first),
        lambda: leave_workspace(membership=second),
    )

    assert sorted(results) == ["completed", "rejected"]
    assert_one_owner_remains(workspace)
