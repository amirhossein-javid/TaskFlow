from html import unescape
from urllib.parse import parse_qs, urlencode, urlsplit

import pytest
from django.urls import reverse

from apps.accounts.models import User
from apps.workspaces.services import create_invitation, create_workspace

pytestmark = pytest.mark.django_db
PASSWORD = "StrongPass!2026Task"


def test_invitation_login_registration_and_acceptance_preserve_destination(client):
    owner = User.objects.create_user("owner@example.com")
    workspace = create_workspace(user=owner, name="Team", slug="team")
    _, token = create_invitation(
        workspace=workspace,
        actor=workspace.memberships.get(user=owner),
        email="invited@example.com",
        role="member",
    )
    destination = reverse("workspaces:invitation", args=[token])
    login = client.get(reverse("accounts:login"), {"next": destination})
    register_url = f"{reverse('accounts:register')}?{urlencode({'next': destination}, safe='/')}"
    assert f'href="{register_url}"' in unescape(login.content.decode())
    # POST-only next must survive a validation error even without a query string.
    payload = {"email": "invited@example.com", "full_name": "عضو", "next": destination}
    invalid = client.post(reverse("accounts:register"), payload)
    assert invalid.status_code == 200
    assert invalid.context["next"] == destination
    assert f'name="next" value="{destination}"' in invalid.content.decode()
    payload.update(password1=PASSWORD, password2=PASSWORD)
    registered = client.post(reverse("accounts:register"), payload)
    assert registered.status_code == 302
    assert parse_qs(urlsplit(registered.url).query)["next"] == [destination]
    logged_in = client.post(
        registered.url,
        {"username": "invited@example.com", "password": PASSWORD, "next": destination},
    )
    assert logged_in.url == destination
    accepted = client.post(logged_in.url)
    assert accepted.url == reverse("workspaces:detail", args=[workspace.slug])
    assert workspace.memberships.filter(user__email="invited@example.com").exists()


@pytest.mark.parametrize(
    "destination", ["https://evil.example/", "//evil.example/", "http://testserver/path"]
)
def test_registration_discards_unsafe_destinations(client, destination):
    response = client.get(reverse("accounts:register"), {"next": destination}, secure=True)
    assert response.context["next"] == ""
    registered = client.post(
        reverse("accounts:register"),
        {
            "email": "new@example.com",
            "full_name": "عضو",
            "password1": PASSWORD,
            "password2": PASSWORD,
            "next": destination,
        },
        secure=True,
    )
    assert registered.url == reverse("accounts:login")


def test_registration_encodes_nested_destination_query_without_loss(client):
    destination = "/workspaces/invitations/token/?a=1&b=two%20words"
    response = client.post(
        reverse("accounts:register"),
        {
            "email": "new@example.com",
            "full_name": "عضو",
            "password1": PASSWORD,
            "password2": PASSWORD,
            "next": destination,
        },
    )
    assert parse_qs(urlsplit(response.url).query)["next"] == [destination]


def test_wrong_account_logout_returns_to_invitation_login(client):
    owner = User.objects.create_user("owner@example.com", PASSWORD)
    workspace = create_workspace(user=owner, name="Team", slug="team")
    _, token = create_invitation(
        workspace=workspace,
        actor=workspace.memberships.get(user=owner),
        email="invited@example.com",
        role="member",
    )
    destination = reverse("workspaces:invitation", args=[token])
    client.force_login(owner)
    page = client.get(destination)
    login_url = f"{reverse('accounts:login')}?{urlencode({'next': destination}, safe='/')}"
    assert f'name="next" value="{login_url}"' in unescape(page.content.decode())
    response = client.post(reverse("accounts:logout"), {"next": login_url})
    assert response.url == login_url
