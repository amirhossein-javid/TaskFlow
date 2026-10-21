from django.conf import settings
from django.contrib.auth import get_user_model
from django.contrib.staticfiles import finders

from apps.accounts.models import Profile
from config.settings import base as base_settings


def test_home_page_uses_persian_rtl_layout(client):
    response = client.get("/")

    assert response.status_code == 200
    assert '<html lang="fa-IR" dir="rtl">' in response.content.decode()
    content = response.content.decode()
    assert "کار تیمی،" in content
    assert "روشن و منظم." in content


def test_theme_bootstrap_precedes_stylesheet_and_exposes_all_preferences(client):
    response = client.get("/")
    content = response.content.decode()

    assert content.index("localStorage.getItem(key)") < content.index('rel="stylesheet"')
    assert 'data-theme-value="light"' in content
    assert 'data-theme-value="dark"' in content
    assert 'data-theme-value="system"' in content
    assert 'src="/static/js/theme' in content
    assert '.js" defer' in content


def test_frontend_assets_and_whitenoise_configuration():
    assert settings.MIDDLEWARE[1] == "whitenoise.middleware.WhiteNoiseMiddleware"
    assert base_settings.STORAGES["staticfiles"]["BACKEND"] == (
        "whitenoise.storage.CompressedManifestStaticFilesStorage"
    )
    assert settings.STORAGES["staticfiles"]["BACKEND"] == (
        "django.contrib.staticfiles.storage.StaticFilesStorage"
    )
    for asset in (
        "css/main.css",
        "js/theme.js",
        "fonts/Vazirmatn-Variable.woff2",
    ):
        assert finders.find(asset) is not None


def test_account_models_use_persian_admin_labels():
    user_model = get_user_model()

    assert str(user_model._meta.verbose_name) == "کاربر"
    assert str(Profile._meta.verbose_name) == "پروفایل"
    assert str(Profile._meta.get_field("full_name").verbose_name) == "نام کامل"
