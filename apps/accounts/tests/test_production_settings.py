import json
import os
import subprocess
import sys

import pytest


def production_settings(**overrides):
    environment = {
        key: value
        for key, value in os.environ.items()
        if not key.startswith(("DJANGO_", "POSTGRES_"))
    }
    environment.update(
        DJANGO_SECRET_KEY="test-only-production-secret-abcdefghijklmnopqrstuvwxyz-0123456789",
        DJANGO_ALLOWED_HOSTS="localhost",
        DJANGO_CSRF_TRUSTED_ORIGINS="https://localhost:8443",
        POSTGRES_DB="taskflow",
        POSTGRES_HOST="db",
        POSTGRES_USER="taskflow_app",
        POSTGRES_PASSWORD="test-only-database-secret-abcdefghijklmnopqrstuvwxyz",
    )
    environment.update(overrides)
    return subprocess.run(
        [
            sys.executable,
            "-c",
            "import json; import config.settings.production as s; "
            "print(json.dumps({k: getattr(s, k) for k in "
            "['DEBUG', 'SECURE_SSL_REDIRECT', 'SESSION_COOKIE_SECURE', 'CSRF_COOKIE_SECURE', "
            "'SECURE_HSTS_PRELOAD', 'SECURE_HSTS_INCLUDE_SUBDOMAINS', 'MEDIA_URL', "
            "'SECURE_PROXY_SSL_HEADER', 'USE_X_FORWARDED_HOST']}))",
        ],
        env=environment,
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )


def test_production_requires_https_and_uses_conservative_security_defaults():
    result = production_settings()
    assert result.returncode == 0, result.stderr
    settings = json.loads(result.stdout)
    assert settings == {
        "DEBUG": False,
        "SECURE_SSL_REDIRECT": True,
        "SESSION_COOKIE_SECURE": True,
        "CSRF_COOKIE_SECURE": True,
        "SECURE_HSTS_PRELOAD": False,
        "SECURE_HSTS_INCLUDE_SUBDOMAINS": False,
        "MEDIA_URL": "/media/",
        "SECURE_PROXY_SSL_HEADER": ["HTTP_X_FORWARDED_PROTO", "https"],
        "USE_X_FORWARDED_HOST": False,
    }


@pytest.mark.parametrize(
    "overrides",
    [
        {"DJANGO_SECRET_KEY": ""},
        {"DJANGO_SECRET_KEY": "unsafe-development-key"},
        {"DJANGO_SECRET_KEY": "a" * 60},
        {"DJANGO_SECRET_KEY": "django-insecure-" + "abcdef" * 10},
        {"DJANGO_ALLOWED_HOSTS": ""},
        {"DJANGO_ALLOWED_HOSTS": "*"},
        {"DJANGO_ALLOWED_HOSTS": ".example.com"},
        {"DJANGO_ALLOWED_HOSTS": "https://localhost:8443"},
        {"DJANGO_DEBUG": "true"},
        {"DJANGO_DEBUG": "typo"},
        {"DJANGO_SECURE_SSL_REDIRECT": "false"},
        {"DJANGO_CSRF_TRUSTED_ORIGINS": "http://localhost:8443"},
        {"DJANGO_CSRF_TRUSTED_ORIGINS": "https://evil.example"},
        {"DJANGO_CSRF_TRUSTED_ORIGINS": "https://user:pass@localhost"},
        {"DJANGO_CSRF_TRUSTED_ORIGINS": "https://localhost/path"},
        {"DJANGO_CSRF_TRUSTED_ORIGINS": "https://localhost:bad"},
        {"POSTGRES_USER": "postgres"},
        {"POSTGRES_HOST": ""},
        {"POSTGRES_PASSWORD": "taskflow"},
        {"DJANGO_SECURE_HSTS_SECONDS": "-1"},
    ],
)
def test_production_rejects_unsafe_configuration(overrides):
    result = production_settings(**overrides)
    assert result.returncode != 0
    assert "RuntimeError" in result.stderr
    assert "test-only-production-secret" not in result.stderr
    assert "test-only-database-secret" not in result.stderr


def test_file_secrets_are_supported_and_ambiguous_sources_are_rejected(tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("file-only-secret-abcdefghijklmnopqrstuvwxyz-0123456789\n")
    assert (
        production_settings(DJANGO_SECRET_KEY="", DJANGO_SECRET_KEY_FILE=str(secret)).returncode
        == 0
    )
    result = production_settings(DJANGO_SECRET_KEY_FILE=str(secret))
    assert result.returncode != 0
    assert "Set exactly one" in result.stderr
    result = production_settings(
        POSTGRES_PASSWORD="",
        POSTGRES_PASSWORD_FILE=str(secret),
    )
    assert result.returncode == 0, result.stderr
