import pytest
from django.test import Client
from django.urls import reverse

from apps.accounts.models import User
from apps.projects.models import Project
from apps.workspaces.models import WorkspaceMembership
from apps.workspaces.services import create_workspace

pytestmark = pytest.mark.django_db


def setup_workspace():
    owner = User.objects.create_user(email="owner@example.com", password="SecurePass123!")
    workspace = create_workspace(user=owner, name="Product", slug="product")
    owner_membership = WorkspaceMembership.objects.get(workspace=workspace, user=owner)
    admin_user = User.objects.create_user(email="admin@example.com", password="SecurePass123!")
    member_user = User.objects.create_user(email="member@example.com", password="SecurePass123!")
    WorkspaceMembership.objects.create(
        workspace=workspace, user=admin_user, role=WorkspaceMembership.Role.ADMIN
    )
    WorkspaceMembership.objects.create(
        workspace=workspace, user=member_user, role=WorkspaceMembership.Role.MEMBER
    )
    return workspace, owner, admin_user, member_user, owner_membership


def test_project_pages_require_authentication(client):
    workspace, *_ = setup_workspace()

    response = client.get(reverse("projects:list", args=[workspace.slug]))

    assert response.status_code == 302
    assert reverse("accounts:login") in response.url


def test_read_only_project_pages_reject_post_and_accept_head(client):
    workspace, owner, *_ = setup_workspace()
    project = Project.objects.create(workspace=workspace, name="Launch", creator=owner)
    client.force_login(owner)
    urls = [
        reverse("projects:list", args=[workspace.slug]),
        reverse("projects:detail", args=[workspace.slug, project.pk]),
    ]

    for url in urls:
        assert client.head(url).status_code == 200
        assert client.post(url).status_code == 405
        assert client.put(url).status_code == 405
        assert client.options(url).status_code == 405


def test_project_form_and_action_views_preserve_original_method_contracts(client):
    workspace, owner, *_ = setup_workspace()
    project = Project.objects.create(workspace=workspace, name="Launch", creator=owner)
    client.force_login(owner)

    get_post_urls = [
        reverse("projects:create", args=[workspace.slug]),
        reverse("projects:edit", args=[workspace.slug, project.pk]),
        reverse("projects:archive", args=[workspace.slug, project.pk]),
    ]
    for url in get_post_urls:
        assert client.get(url).status_code == 200
        assert client.put(url).status_code == 405
        assert client.head(url).status_code == 405
        assert client.options(url).status_code == 405

    post_only_url = reverse("projects:restore", args=[workspace.slug, project.pk])
    assert client.get(post_only_url).status_code == 405
    assert client.put(post_only_url).status_code == 405
    assert client.head(post_only_url).status_code == 405
    assert client.options(post_only_url).status_code == 405


@pytest.mark.parametrize("user_index", [1, 2])
def test_owner_and_admin_can_create_projects(client, user_index):
    workspace, owner, admin, *_ = setup_workspace()
    client.force_login([owner, admin][user_index - 1])

    response = client.post(
        reverse("projects:create", args=[workspace.slug]),
        {"name": "Launch", "description": "Release project"},
    )

    assert response.status_code == 302
    assert Project.objects.filter(workspace=workspace, name="Launch").exists()


def test_member_can_view_but_cannot_manage_projects(client):
    workspace, owner, _, member, _ = setup_workspace()
    project = Project.objects.create(workspace=workspace, name="Launch", creator=owner)
    client.force_login(member)

    assert client.get(reverse("projects:list", args=[workspace.slug])).status_code == 200
    assert (
        client.get(reverse("projects:detail", args=[workspace.slug, project.pk])).status_code == 200
    )
    assert client.get(reverse("projects:create", args=[workspace.slug])).status_code == 403
    assert (
        client.post(reverse("projects:archive", args=[workspace.slug, project.pk])).status_code
        == 403
    )


def test_non_member_cannot_access_project_data(client):
    workspace, owner, *_ = setup_workspace()
    project = Project.objects.create(workspace=workspace, name="Secret", creator=owner)
    outsider = User.objects.create_user(email="outsider@example.com", password="SecurePass123!")
    client.force_login(outsider)

    assert client.get(reverse("projects:list", args=[workspace.slug])).status_code == 404
    assert (
        client.get(reverse("projects:detail", args=[workspace.slug, project.pk])).status_code == 404
    )


def test_project_id_cannot_cross_workspace_boundary(client):
    first_workspace, first_owner, *_ = setup_workspace()
    second_owner = User.objects.create_user(email="second@example.com", password="SecurePass123!")
    second_workspace = create_workspace(user=second_owner, name="Second", slug="second")
    foreign_project = Project.objects.create(
        workspace=second_workspace, name="Foreign", creator=second_owner
    )
    client.force_login(first_owner)

    response = client.get(
        reverse("projects:detail", args=[first_workspace.slug, foreign_project.pk])
    )

    assert response.status_code == 404


def test_list_separates_active_and_archived_projects(client):
    workspace, owner, *_ = setup_workspace()
    active = Project.objects.create(workspace=workspace, name="Active", creator=owner)
    archived = Project.objects.create(
        workspace=workspace,
        name="Archived",
        creator=owner,
        status=Project.Status.ARCHIVED,
    )
    client.force_login(owner)

    response = client.get(reverse("projects:list", args=[workspace.slug]))

    assert list(response.context["active_projects"]) == [active]
    assert list(response.context["archived_projects"]) == [archived]


def test_archive_and_restore_require_post_for_state_change(client):
    workspace, owner, *_ = setup_workspace()
    project = Project.objects.create(workspace=workspace, name="Launch", creator=owner)
    client.force_login(owner)

    archive_url = reverse("projects:archive", args=[workspace.slug, project.pk])
    assert client.get(archive_url).status_code == 200
    project.refresh_from_db()
    assert project.status == Project.Status.ACTIVE

    assert client.post(archive_url).status_code == 302
    project.refresh_from_db()
    assert project.status == Project.Status.ARCHIVED

    restore_url = reverse("projects:restore", args=[workspace.slug, project.pk])
    assert client.get(restore_url).status_code == 405
    assert client.post(restore_url).status_code == 302
    project.refresh_from_db()
    assert project.status == Project.Status.ACTIVE


def test_archived_project_cannot_be_edited(client):
    workspace, owner, *_ = setup_workspace()
    project = Project.objects.create(
        workspace=workspace,
        name="Archived",
        creator=owner,
        status=Project.Status.ARCHIVED,
    )
    client.force_login(owner)
    url = reverse("projects:edit", args=[workspace.slug, project.pk])

    get_response = client.get(url)
    post_response = client.post(url, {"name": "Changed", "description": ""})

    assert get_response.status_code == 302
    assert post_response.status_code == 302
    project.refresh_from_db()
    assert project.name == "Archived"


def test_manager_can_edit_active_project(client):
    workspace, _, admin, *_ = setup_workspace()
    project = Project.objects.create(workspace=workspace, name="Launch", creator=admin)
    client.force_login(admin)

    response = client.post(
        reverse("projects:edit", args=[workspace.slug, project.pk]),
        {"name": "Launch updated", "description": "New scope"},
    )

    assert response.status_code == 302
    project.refresh_from_db()
    assert project.name == "Launch updated"
    assert project.description == "New scope"


def test_invalid_project_form_shows_persian_error(client):
    workspace, owner, *_ = setup_workspace()
    client.force_login(owner)

    response = client.post(
        reverse("projects:create", args=[workspace.slug]),
        {"name": "   ", "description": ""},
    )

    assert response.status_code == 200
    assert "نام پروژه نمی‌تواند خالی باشد" in response.content.decode()
    assert not Project.objects.filter(workspace=workspace).exists()


def test_cross_workspace_project_cannot_be_edited_or_archived(client):
    first_workspace, first_owner, *_ = setup_workspace()
    second_owner = User.objects.create_user(
        email="second-manager@example.com", password="SecurePass123!"
    )
    second_workspace = create_workspace(user=second_owner, name="Second", slug="second")
    foreign_project = Project.objects.create(
        workspace=second_workspace, name="Foreign", creator=second_owner
    )
    client.force_login(first_owner)

    edit_response = client.post(
        reverse("projects:edit", args=[first_workspace.slug, foreign_project.pk]),
        {"name": "Compromised", "description": ""},
    )
    archive_response = client.post(
        reverse("projects:archive", args=[first_workspace.slug, foreign_project.pk])
    )

    assert edit_response.status_code == 404
    assert archive_response.status_code == 404
    foreign_project.refresh_from_db()
    assert foreign_project.name == "Foreign"
    assert foreign_project.status == Project.Status.ACTIVE


def test_workspace_detail_links_projects_and_shows_active_count(client):
    workspace, owner, *_ = setup_workspace()
    Project.objects.create(workspace=workspace, name="Active", creator=owner)
    Project.objects.create(
        workspace=workspace,
        name="Archived",
        creator=owner,
        status=Project.Status.ARCHIVED,
    )
    client.force_login(owner)

    response = client.get(reverse("workspaces:detail", args=[workspace.slug]))
    content = response.content.decode()

    assert response.context["active_project_count"] == 1
    assert reverse("projects:list", args=[workspace.slug]) in content
    assert reverse("projects:create", args=[workspace.slug]) in content


def test_archive_endpoint_rejects_missing_csrf_token():
    workspace, owner, *_ = setup_workspace()
    project = Project.objects.create(workspace=workspace, name="Launch", creator=owner)
    csrf_client = Client(enforce_csrf_checks=True)
    csrf_client.force_login(owner)

    response = csrf_client.post(reverse("projects:archive", args=[workspace.slug, project.pk]))

    assert response.status_code == 403
    project.refresh_from_db()
    assert project.status == Project.Status.ACTIVE
