from concurrent.futures import ThreadPoolExecutor
from queue import Queue
from threading import Barrier, Event
from time import monotonic
from unittest.mock import patch

import pytest
from django.db import close_old_connections, connection, transaction
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.workspaces.models import Workspace
from apps.workspaces.services import create_workspace, delete_workspace
from apps.workspaces.views import WorkspaceDeleteView, WorkspaceSettingsView

pytestmark = pytest.mark.django_db(transaction=True)


@pytest.mark.parametrize("route", ["settings", "delete"])
@pytest.mark.parametrize("timing", ["before_lock", "waiting_for_lock"])
def test_concurrency_workspace_disappearance_returns_404_after_initial_lookup(route, timing):
    owner = User.objects.create_user("owner@example.com")
    workspace = create_workspace(user=owner, name="Original", slug="original")
    actor = workspace.memberships.get(user=owner)
    workspace_id = workspace.pk
    dispatched = Barrier(2)
    allow_service = Event()
    lock_attempted = Event()
    backend_ids = Queue()
    view = WorkspaceSettingsView if route == "settings" else WorkspaceDeleteView
    original_form_valid = view.form_valid

    def after_lookup(self, form):
        # Authentication, scoped lookup, permission checks, and form validation
        # have all completed before the workspace disappears.
        dispatched.wait(timeout=5)
        assert allow_service.wait(timeout=5)
        return original_form_valid(self, form)

    def observe_service_lock(execute, sql, params, many, context):
        if 'FROM "workspaces_workspace"' in sql and "FOR UPDATE" in sql:
            lock_attempted.set()
        return execute(sql, params, many, context)

    def request():
        close_old_connections()
        try:
            with connection.cursor() as cursor:
                cursor.execute("SET lock_timeout = '5s'")
                cursor.execute("SET statement_timeout = '10s'")
                cursor.execute("SELECT pg_backend_pid()")
                backend_ids.put(cursor.fetchone()[0])
            client = Client()
            client.force_login(owner)
            with connection.execute_wrapper(observe_service_lock):
                return client.post(
                    reverse(f"workspaces:{route}", args=[workspace.slug]),
                    {"name": "Changed", "slug": "changed", "confirmation": "Original"},
                ).status_code
        finally:
            connection.close()

    with patch.object(view, "form_valid", after_lookup):
        with ThreadPoolExecutor(max_workers=1) as executor:
            try:
                with transaction.atomic():
                    with connection.cursor() as cursor:
                        cursor.execute("SET LOCAL lock_timeout = '5s'")
                        cursor.execute("SET LOCAL statement_timeout = '10s'")
                        cursor.execute("SELECT pg_backend_pid()")
                        deleting_backend = cursor.fetchone()[0]
                    Workspace.objects.select_for_update().get(pk=workspace_id)
                    future = executor.submit(request)
                    requesting_backend = backend_ids.get(timeout=5)
                    assert deleting_backend != requesting_backend
                    dispatched.wait(timeout=5)
                    if timing == "waiting_for_lock":
                        allow_service.set()
                        assert lock_attempted.wait(timeout=5)
                        deadline = monotonic() + 3
                        while True:
                            with connection.cursor() as cursor:
                                cursor.execute(
                                    "SELECT %s = ANY(pg_blocking_pids(%s))",
                                    [deleting_backend, requesting_backend],
                                )
                                if cursor.fetchone()[0]:
                                    break
                            assert monotonic() < deadline, (
                                "Request did not wait for the workspace lock"
                            )
                            Event().wait(0.01)
                    delete_workspace(workspace=workspace, actor=actor, confirmation="Original")
            finally:
                # In the before_lock case the deletion commits before allowing
                # the stale request to enter its transaction at all.
                allow_service.set()
            assert future.result(timeout=15) == 404
    assert not Workspace.objects.filter(pk=workspace_id).exists()
    assert not Workspace.objects.filter(slug="changed").exists()
