from io import StringIO

import pytest
from django.core.management import call_command
from django.db import transaction
from django.db.models.deletion import ProtectedError
from django.urls import reverse

from apps.accounts.models import Profile, User

pytestmark = pytest.mark.django_db


@pytest.fixture
def profile_admin(client):
    admin = User.objects.create_superuser("profile-admin@example.com", "SecurePass123!")
    client.force_login(admin)
    return admin


def test_admin_user_creation_creates_exactly_one_profile(client, profile_admin):
    response = client.post(
        reverse("admin:accounts_user_add"),
        {
            "email": "admin-created@example.com",
            "password1": "SecurePass123!",
            "password2": "SecurePass123!",
            "is_active": "on",
            "_save": "Save",
        },
    )
    assert response.status_code == 302
    user = User.objects.get(email="admin-created@example.com")
    assert user.check_password("SecurePass123!")
    assert Profile.objects.filter(user=user).count() == 1


@pytest.mark.parametrize("queryset", [False, True])
def test_independent_profile_deletion_is_protected(queryset):
    user = User.objects.create_user("protected@example.com")
    profile = user.profile
    with pytest.raises(ProtectedError, match="پروفایل فقط همراه"), transaction.atomic():
        if queryset:
            Profile.objects.filter(pk=profile.pk).delete()
        else:
            profile.delete()
    assert Profile.objects.filter(user=user).count() == 1
    assert User.objects.filter(pk=user.pk).exists()


def test_user_queryset_deletion_still_cascades_to_profiles():
    user = User.objects.create_user("cascade@example.com")
    user_id = user.pk
    User.objects.filter(pk=user_id).delete()
    assert not User.objects.filter(pk=user_id).exists()
    assert not Profile.objects.filter(user_id=user_id).exists()


def test_profile_admin_disallows_single_and_bulk_deletion(client, profile_admin):
    user = User.objects.create_user("protected@example.com")
    profile = user.profile
    delete_url = reverse("admin:accounts_profile_delete", args=[profile.pk])
    assert client.get(delete_url).status_code == 403
    assert client.post(delete_url, {"post": "yes"}).status_code == 403
    response = client.get(reverse("admin:accounts_profile_changelist"))
    assert response.context["action_form"] is None
    response = client.post(
        reverse("admin:accounts_profile_changelist"),
        {
            "action": "delete_selected",
            "_selected_action": [profile.pk],
            "post": "yes",
        },
    )
    assert response.status_code == 200
    assert Profile.objects.filter(user=user).count() == 1


def test_profile_admin_allows_editing_but_preserves_owner(client, profile_admin):
    user = User.objects.create_user("protected@example.com")
    other = User.objects.bulk_create([User(email="missing@example.com")])[0]
    profile = user.profile
    url = reverse("admin:accounts_profile_change", args=[profile.pk])
    response = client.get(url)
    assert "user" not in response.context["adminform"].form.fields
    response = client.post(url, {"user": other.pk, "full_name": "نام تازه", "bio": "متن تازه"})
    assert response.status_code == 302
    profile.refresh_from_db()
    assert profile.user_id == user.pk
    assert profile.full_name == "نام تازه"
    assert profile.bio == "متن تازه"
    assert not Profile.objects.filter(user=other).exists()


@pytest.mark.parametrize("bulk", [False, True])
def test_user_admin_deletion_still_cascades_to_profiles(client, profile_admin, bulk):
    user = User.objects.create_user("cascade@example.com")
    user_id = user.pk
    if bulk:
        response = client.post(
            reverse("admin:accounts_user_changelist"),
            {
                "action": "delete_selected",
                "_selected_action": [user_id],
                "post": "yes",
            },
        )
    else:
        url = reverse("admin:accounts_user_delete", args=[user_id])
        assert client.get(url).status_code == 200
        response = client.post(url, {"post": "yes"})
    assert response.status_code == 302
    assert not User.objects.filter(pk=user_id).exists()
    assert not Profile.objects.filter(user_id=user_id).exists()


def test_repair_profiles_is_idempotent_and_preserves_existing_data():
    healthy = User.objects.create_user("healthy@example.com")
    Profile.objects.filter(user=healthy).update(
        full_name="Existing name", bio="Existing biography", avatar="avatars/existing.png"
    )
    original_profile = Profile.objects.filter(user=healthy).values().get()
    missing = User.objects.bulk_create(
        [
            User(email="missing@example.com"),
            User(email="inactive@example.com", is_active=False),
        ]
    )
    original_users = list(User.objects.order_by("pk").values())
    for expected_count in [2, 0]:
        output = StringIO()
        call_command("repair_profiles", stdout=output)
        assert output.getvalue().strip() == f"تعداد پروفایل‌های ساخته‌شده: {expected_count}"
        assert Profile.objects.count() == User.objects.count()
        assert Profile.objects.filter(user=healthy).values().get() == original_profile
        assert list(User.objects.order_by("pk").values()) == original_users
    for user in missing:
        profile = Profile.objects.get(user=user)
        assert (profile.full_name, profile.bio, profile.avatar.name) == ("", "", "")


def test_repair_profiles_handles_an_empty_database():
    output = StringIO()
    call_command("repair_profiles", stdout=output)
    assert "0" in output.getvalue()
    assert not Profile.objects.exists()


def test_objects_create_and_repeated_save_preserve_exactly_one_profile():
    user = User.objects.create(email="direct-create@example.com")
    profile = user.profile
    Profile.objects.filter(pk=profile.pk).update(full_name="Existing name")
    user.save(update_fields=["is_active"])
    assert Profile.objects.filter(user=user).count() == 1
    profile.refresh_from_db()
    assert profile.full_name == "Existing name"


def test_raw_user_save_skips_profile_creation_until_explicit_repair():
    user = User(email="raw@example.com")
    user.save_base(raw=True)
    assert not Profile.objects.filter(user=user).exists()
    call_command("repair_profiles", stdout=StringIO())
    assert Profile.objects.filter(user=user).count() == 1
