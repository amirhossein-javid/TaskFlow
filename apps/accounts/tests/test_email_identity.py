from unittest.mock import patch

import pytest
from django.db import IntegrityError, transaction
from django.urls import reverse

from apps.accounts.forms import UserChangeForm, UserCreationForm
from apps.accounts.models import User

pytestmark = pytest.mark.django_db
PASSWORD = "StrongPass!2026Task"


def test_model_save_and_clean_normalize_email():
    user = User.objects.create(email="  Mixed@EXAMPLE.COM  ")
    user.refresh_from_db()
    assert user.email == "mixed@example.com"
    user.email = " Updated@EXAMPLE.COM "
    user.full_clean(exclude=["password"])
    assert user.email == "updated@example.com"
    user.save(update_fields=["email"])
    user.refresh_from_db()
    assert user.email == "updated@example.com"


@pytest.mark.parametrize("email", ["PERSON@example.com", " person@EXAMPLE.com "])
def test_database_rejects_unnormalized_duplicate_email(email):
    User.objects.create_user("person@example.com")
    with pytest.raises(IntegrityError), transaction.atomic():
        User.objects.bulk_create([User(email=email)])
    assert User.objects.count() == 1


def test_admin_forms_share_email_identity_validation():
    user = User.objects.create_user("person@example.com")
    other = User.objects.create_user("other@example.com")
    creation = UserCreationForm(
        data={"email": "PERSON@EXAMPLE.COM", "password1": PASSWORD, "password2": PASSWORD}
    )
    assert not creation.is_valid()
    assert "کاربری با این ایمیل وجود دارد." in creation.errors["email"]
    change = UserChangeForm(instance=other, data={"email": "PERSON@EXAMPLE.COM"})
    assert not change.is_valid()
    assert "email" in change.errors
    own = UserChangeForm(instance=user, data={"email": "PERSON@EXAMPLE.COM"})
    assert own.is_valid(), own.errors
    assert own.save().email == "person@example.com"


def test_login_accepts_email_case_and_whitespace(client):
    user = User.objects.create_user("person@example.com", PASSWORD)
    response = client.post(
        reverse("accounts:login"), {"username": " PERSON@EXAMPLE.COM ", "password": PASSWORD}
    )
    assert response.status_code == 302
    assert client.session["_auth_user_id"] == str(user.pk)


def test_admin_creation_normalizes_email(client):
    admin = User.objects.create_superuser("admin@example.com", PASSWORD)
    client.force_login(admin)
    response = client.post(
        reverse("admin:accounts_user_add"),
        {
            "email": " Mixed@EXAMPLE.COM ",
            "password1": PASSWORD,
            "password2": PASSWORD,
            "is_active": "on",
        },
    )
    assert response.status_code == 302
    assert User.objects.get(email="mixed@example.com").profile is not None


def test_registration_does_not_hide_unrelated_database_errors(client):
    with patch("apps.accounts.forms.RegistrationForm.save", side_effect=IntegrityError("other")):
        with pytest.raises(IntegrityError):
            client.post(
                reverse("accounts:register"),
                {
                    "email": "person@example.com",
                    "full_name": "کاربر",
                    "password1": PASSWORD,
                    "password2": PASSWORD,
                },
            )


def test_admin_does_not_hide_unrelated_database_errors(client):
    admin = User.objects.create_superuser("admin@example.com", PASSWORD)
    client.force_login(admin)
    with patch("apps.accounts.admin.UserAdmin.save_model", side_effect=IntegrityError("other")):
        with pytest.raises(IntegrityError):
            client.post(
                reverse("admin:accounts_user_add"),
                {"email": "person@example.com", "password1": PASSWORD, "password2": PASSWORD},
            )
