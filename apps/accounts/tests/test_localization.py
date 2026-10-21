from django.contrib.auth import get_user_model

from apps.accounts.models import Profile


def test_home_page_uses_persian_rtl_layout(client):
    response = client.get("/")

    assert response.status_code == 200
    assert '<html lang="fa-IR" dir="rtl">' in response.content.decode()
    assert "فضای کاری تیم شما آماده است." in response.content.decode()


def test_account_models_use_persian_admin_labels():
    user_model = get_user_model()

    assert str(user_model._meta.verbose_name) == "کاربر"
    assert str(Profile._meta.verbose_name) == "پروفایل"
    assert str(Profile._meta.get_field("full_name").verbose_name) == "نام کامل"
