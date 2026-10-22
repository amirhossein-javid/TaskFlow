from io import BytesIO

import pytest
from django.contrib.auth import get_user_model
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import Client, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode
from PIL import Image

from apps.accounts.forms import ProfileForm
from apps.accounts.models import Profile

User = get_user_model()
PASSWORD = "StrongPass!2026Task"
NEW_PASSWORD = "NewStrongPass!2026Task"


def create_user(email="person@example.com", password=PASSWORD):
    return User.objects.create_user(email, password)


def image_upload(image_format="PNG", content_type="image/png"):
    image_data = BytesIO()
    Image.new("RGB", (24, 24), color="#4f46e5").save(image_data, format=image_format)
    image_data.seek(0)
    return SimpleUploadedFile(
        f"avatar.{image_format.lower()}",
        image_data.read(),
        content_type=content_type,
    )


@pytest.mark.django_db
def test_registration_creates_user_and_populates_profile(client):
    response = client.post(
        reverse("accounts:register"),
        {
            "email": "NewUser@EXAMPLE.COM",
            "full_name": "کاربر جدید",
            "password1": PASSWORD,
            "password2": PASSWORD,
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("accounts:login")
    user = User.objects.get(email="newuser@example.com")
    assert user.check_password(PASSWORD) is True
    assert user.profile.full_name == "کاربر جدید"
    assert Profile.objects.filter(user=user).count() == 1


@pytest.mark.django_db
def test_registration_rejects_case_insensitive_duplicate_email(client):
    create_user("person@example.com")

    response = client.post(
        reverse("accounts:register"),
        {
            "email": "PERSON@example.com",
            "full_name": "کاربر دوم",
            "password1": PASSWORD,
            "password2": PASSWORD,
        },
    )

    assert response.status_code == 200
    assert "کاربری با این ایمیل وجود دارد." in response.content.decode()
    assert User.objects.count() == 1


@pytest.mark.django_db
def test_registration_applies_password_validation(client):
    response = client.post(
        reverse("accounts:register"),
        {
            "email": "person@example.com",
            "full_name": "کاربر آزمایشی",
            "password1": "password",
            "password2": "password",
        },
    )

    assert response.status_code == 200
    assert User.objects.exists() is False
    assert "این رمز عبور بسیار رایج است." in response.content.decode()


@pytest.mark.django_db
def test_registration_requires_csrf_token():
    csrf_client = Client(enforce_csrf_checks=True)

    response = csrf_client.post(
        reverse("accounts:register"),
        {
            "email": "person@example.com",
            "full_name": "کاربر آزمایشی",
            "password1": PASSWORD,
            "password2": PASSWORD,
        },
    )

    assert response.status_code == 403
    assert User.objects.exists() is False


@pytest.mark.django_db
def test_login_and_post_only_logout(client):
    user = create_user()

    login_response = client.post(
        reverse("accounts:login"),
        {"username": user.email, "password": PASSWORD},
    )

    assert login_response.status_code == 302
    assert login_response.url == reverse("accounts:profile")
    assert str(client.session["_auth_user_id"]) == str(user.pk)
    assert client.get(reverse("accounts:logout")).status_code == 405

    logout_response = client.post(reverse("accounts:logout"))
    assert logout_response.status_code == 302
    assert "_auth_user_id" not in client.session


@pytest.mark.django_db
def test_login_rejects_external_next_redirect(client):
    user = create_user()

    response = client.post(
        f"{reverse('accounts:login')}?next=https://malicious.example/path",
        {"username": user.email, "password": PASSWORD},
    )

    assert response.status_code == 302
    assert response.url == reverse("accounts:profile")


@pytest.mark.django_db
def test_profile_page_requires_authentication(client):
    response = client.get(reverse("accounts:profile"))

    assert response.status_code == 302
    assert response.url.startswith(reverse("accounts:login"))


@pytest.mark.django_db
def test_profile_update_persists_fields(client):
    user = create_user()
    client.force_login(user)

    response = client.post(
        reverse("accounts:profile"),
        {"full_name": "نام تازه", "bio": "دربارهٔ کاربر"},
    )

    assert response.status_code == 302
    user.profile.refresh_from_db()
    assert user.profile.full_name == "نام تازه"
    assert user.profile.bio == "دربارهٔ کاربر"


@pytest.mark.django_db
def test_profile_accepts_valid_avatar(client, tmp_path):
    user = create_user()
    client.force_login(user)

    with override_settings(MEDIA_ROOT=tmp_path):
        response = client.post(
            reverse("accounts:profile"),
            {"full_name": "نام کاربر", "bio": "", "avatar": image_upload()},
        )

    assert response.status_code == 302
    user.profile.refresh_from_db()
    assert user.profile.avatar.name.startswith("avatars/avatar")


@pytest.mark.django_db
def test_profile_rejects_unsupported_avatar_format(client):
    user = create_user()
    client.force_login(user)

    response = client.post(
        reverse("accounts:profile"),
        {
            "full_name": "نام کاربر",
            "bio": "",
            "avatar": image_upload("GIF", "image/gif"),
        },
    )

    assert response.status_code == 200
    assert "فرمت تصویر باید JPEG، PNG یا WebP باشد." in response.content.decode()


@pytest.mark.django_db
def test_profile_rejects_oversized_avatar():
    user = create_user()
    avatar = image_upload()
    avatar.size = ProfileForm.max_avatar_size + 1

    form = ProfileForm(
        data={"full_name": "نام کاربر", "bio": ""},
        files={"avatar": avatar},
        instance=user.profile,
    )

    assert form.is_valid() is False
    assert "حجم تصویر پروفایل نباید بیشتر از ۲ مگابایت باشد." in form.errors["avatar"]


@pytest.mark.django_db
def test_password_change_updates_password_and_keeps_session(client):
    user = create_user()
    client.force_login(user)

    response = client.post(
        reverse("accounts:password_change"),
        {
            "old_password": PASSWORD,
            "new_password1": NEW_PASSWORD,
            "new_password2": NEW_PASSWORD,
        },
    )

    assert response.status_code == 302
    assert response.url == reverse("accounts:password_change_done")
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD) is True
    assert str(client.session["_auth_user_id"]) == str(user.pk)


@pytest.mark.django_db
@override_settings(EMAIL_BACKEND="django.core.mail.backends.locmem.EmailBackend")
def test_password_reset_sends_email_without_account_disclosure(client):
    create_user()

    known_response = client.post(
        reverse("accounts:password_reset"),
        {"email": "person@example.com"},
    )
    assert known_response.status_code == 302
    assert known_response.url == reverse("accounts:password_reset_done")
    assert len(mail.outbox) == 1
    assert "/accounts/password/reset/" in mail.outbox[0].body

    mail.outbox.clear()
    unknown_response = client.post(
        reverse("accounts:password_reset"),
        {"email": "unknown@example.com"},
    )
    assert unknown_response.status_code == 302
    assert unknown_response.url == reverse("accounts:password_reset_done")
    assert mail.outbox == []


@pytest.mark.django_db
def test_password_reset_token_is_single_use(client):
    user = create_user()
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    reset_url = reverse(
        "accounts:password_reset_confirm",
        kwargs={"uidb64": uid, "token": token},
    )

    token_response = client.get(reset_url)
    assert token_response.status_code == 302

    reset_response = client.post(
        token_response.url,
        {"new_password1": NEW_PASSWORD, "new_password2": NEW_PASSWORD},
    )
    assert reset_response.status_code == 302
    assert reset_response.url == reverse("accounts:password_reset_complete")
    user.refresh_from_db()
    assert user.check_password(NEW_PASSWORD) is True

    reused_response = client.get(reset_url, follow=True)
    assert reused_response.status_code == 200
    assert "این لینک استفاده شده یا اعتبار آن پایان یافته است." in reused_response.content.decode()


@pytest.mark.django_db
def test_invalid_password_reset_token_is_rejected(client):
    user = create_user()
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    invalid_url = reverse(
        "accounts:password_reset_confirm",
        kwargs={"uidb64": uid, "token": "invalid-token"},
    )

    response = client.get(invalid_url)

    assert response.status_code == 200
    assert "این لینک استفاده شده یا اعتبار آن پایان یافته است." in response.content.decode()
