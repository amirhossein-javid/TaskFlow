import pytest
from django.contrib.auth import get_user_model
from django.core.exceptions import ValidationError
from django.core.management import call_command
from django.db import IntegrityError, transaction

from apps.accounts.forms import UserCreationForm
from apps.accounts.models import Profile

User = get_user_model()


@pytest.mark.django_db
def test_create_user_normalizes_email_and_creates_profile():
    user = User.objects.create_user("Person@EXAMPLE.COM", "a-secure-password")

    assert user.email == "Person@example.com"
    assert user.is_active is True
    assert user.is_staff is False
    assert user.is_superuser is False
    assert Profile.objects.filter(user=user).count() == 1
    assert user.profile.full_name == ""
    assert user.profile.bio == ""
    assert user.profile.avatar.name == ""


@pytest.mark.django_db
def test_create_user_hashes_password():
    user = User.objects.create_user("person@example.com", "plain-password")

    assert user.password != "plain-password"
    assert user.check_password("plain-password") is True


@pytest.mark.django_db
def test_create_superuser_sets_required_flags_and_creates_profile():
    user = User.objects.create_superuser("admin@example.com", "secure-password")

    assert user.is_staff is True
    assert user.is_superuser is True
    assert user.is_active is True
    assert user.profile.user == user


@pytest.mark.django_db
def test_createsuperuser_command_creates_profile(monkeypatch):
    monkeypatch.setenv("DJANGO_SUPERUSER_EMAIL", "command-admin@example.com")
    monkeypatch.setenv("DJANGO_SUPERUSER_PASSWORD", "secure-password")

    call_command("createsuperuser", interactive=False, verbosity=0)

    user = User.objects.get(email="command-admin@example.com")
    assert user.check_password("secure-password") is True
    assert user.profile.user_id == user.pk


@pytest.mark.django_db
def test_email_must_be_unique():
    User.objects.create_user("person@example.com", "secure-password")

    with pytest.raises(ValidationError):
        User.objects.create_user("person@example.com", "secure-password")


@pytest.mark.django_db
def test_create_user_requires_email():
    with pytest.raises(ValueError, match="ایمیل"):
        User.objects.create_user("", "secure-password")


@pytest.mark.django_db
@pytest.mark.parametrize(
    ("field", "message"),
    [
        ("is_staff", "دسترسی ورود به بخش مدیریت"),
        ("is_superuser", "همهٔ مجوزها"),
    ],
)
def test_create_superuser_rejects_false_privilege_flags(field, message):
    with pytest.raises(ValueError, match=message):
        User.objects.create_superuser(
            "admin@example.com",
            "secure-password",
            **{field: False},
        )


@pytest.mark.django_db
def test_create_superuser_requires_password():
    with pytest.raises(ValueError, match="رمز عبور"):
        User.objects.create_superuser("admin@example.com", "")


@pytest.mark.django_db
def test_direct_user_save_creates_exactly_one_profile():
    user = User(email="direct@example.com")
    user.set_password("secure-password")
    user.save()
    user.save(update_fields=["is_active"])

    assert Profile.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_admin_creation_form_creates_profile():
    form = UserCreationForm(
        data={
            "email": "admin-form@example.com",
            "password1": "a-secure-password",
            "password2": "a-secure-password",
        }
    )

    assert form.is_valid(), form.errors
    user = form.save()
    assert user.profile.user_id == user.pk


@pytest.mark.django_db
def test_user_creation_form_uses_persian_labels_and_validation():
    form = UserCreationForm(
        data={
            "email": "mismatch@example.com",
            "password1": "first-password",
            "password2": "second-password",
        }
    )

    assert form.fields["password1"].label == "رمز عبور"
    assert form.fields["password2"].label == "تکرار رمز عبور"
    assert form.is_valid() is False
    assert "رمزهای عبور یکسان نیستند." in form.errors["password2"]


@pytest.mark.django_db
def test_profile_user_relationship_is_unique():
    user = User.objects.create_user("person@example.com", "secure-password")

    with pytest.raises(IntegrityError), transaction.atomic():
        Profile.objects.create(user=user)


@pytest.mark.django_db
def test_deleting_user_cascades_to_profile():
    user = User.objects.create_user("person@example.com", "secure-password")
    profile_id = user.profile.pk

    user.delete()

    assert Profile.objects.filter(pk=profile_id).exists() is False


@pytest.mark.django_db
def test_profile_fields_persist():
    user = User.objects.create_user("person@example.com", "secure-password")
    profile = user.profile
    profile.full_name = "Test Person"
    profile.bio = "A short biography."
    profile.save()
    profile.refresh_from_db()

    assert profile.full_name == "Test Person"
    assert profile.bio == "A short biography."
    assert str(profile) == "Test Person"


@pytest.mark.django_db
def test_profile_string_falls_back_to_email():
    user = User.objects.create_user("person@example.com", "secure-password")

    assert str(user.profile) == user.email


@pytest.mark.django_db
def test_bulk_create_does_not_emit_profile_signal():
    user = User(email="bulk@example.com")
    user.set_password("secure-password")

    User.objects.bulk_create([user])

    assert Profile.objects.filter(user=user).exists() is False
