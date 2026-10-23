import math
import os
from email.utils import parseaddr
from pathlib import Path

from django.core.exceptions import ValidationError
from django.core.validators import validate_email

BASE_DIR = Path(__file__).resolve().parents[2]


def env(name: str, default: str | None = None) -> str:
    value = os.environ.get(name, default)
    if value is None:
        raise RuntimeError(f"Required environment variable {name} is not set.")
    return value


def env_bool(name: str, default: bool = False, *, strict: bool = False) -> bool:
    value = env(name, str(default)).lower()
    if strict and value not in {"1", "true", "yes", "on", "0", "false", "no", "off"}:
        raise RuntimeError(f"{name} must be a boolean.")
    return value in {"1", "true", "yes", "on"}


def env_list(name: str, default: str = "") -> list[str]:
    return [item.strip() for item in env(name, default).split(",") if item.strip()]


SECRET_KEY = env("DJANGO_SECRET_KEY", "unsafe-development-key")
DEBUG = False
ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS", "localhost,127.0.0.1")

INSTALLED_APPS = [
    "django.contrib.admin",
    "django.contrib.auth",
    "django.contrib.contenttypes",
    "django.contrib.sessions",
    "django.contrib.messages",
    "django.contrib.staticfiles",
    "apps.accounts.apps.AccountsConfig",
    "apps.workspaces.apps.WorkspacesConfig",
    "apps.projects.apps.ProjectsConfig",
    "apps.boards.apps.BoardsConfig",
    "apps.notifications.apps.NotificationsConfig",
]

MIDDLEWARE = [
    "django.middleware.security.SecurityMiddleware",
    "whitenoise.middleware.WhiteNoiseMiddleware",
    "django.contrib.sessions.middleware.SessionMiddleware",
    "django.middleware.common.CommonMiddleware",
    "django.middleware.csrf.CsrfViewMiddleware",
    "django.contrib.auth.middleware.AuthenticationMiddleware",
    "django.contrib.messages.middleware.MessageMiddleware",
    "django.middleware.clickjacking.XFrameOptionsMiddleware",
]

ROOT_URLCONF = "config.urls"
TEMPLATES = [
    {
        "BACKEND": "django.template.backends.django.DjangoTemplates",
        "DIRS": [BASE_DIR / "templates"],
        "APP_DIRS": True,
        "OPTIONS": {
            "context_processors": [
                "django.template.context_processors.request",
                "django.contrib.auth.context_processors.auth",
                "django.contrib.messages.context_processors.messages",
                "apps.workspaces.context_processors.workspace_navigation",
                "apps.notifications.context_processors.notification_navigation",
            ],
        },
    },
]
WSGI_APPLICATION = "config.wsgi.application"
ASGI_APPLICATION = "config.asgi.application"

DATABASES = {
    "default": {
        "ENGINE": "django.db.backends.postgresql",
        "NAME": env("POSTGRES_DB", "taskflow"),
        "USER": env("POSTGRES_USER", "taskflow"),
        "PASSWORD": env("POSTGRES_PASSWORD", "taskflow"),
        "HOST": env("POSTGRES_HOST", "localhost"),
        "PORT": env("POSTGRES_PORT", "5432"),
        "CONN_MAX_AGE": int(env("POSTGRES_CONN_MAX_AGE", "60")),
        "CONN_HEALTH_CHECKS": True,
    }
}

AUTH_PASSWORD_VALIDATORS = [
    {"NAME": "django.contrib.auth.password_validation.UserAttributeSimilarityValidator"},
    {"NAME": "django.contrib.auth.password_validation.MinimumLengthValidator"},
    {"NAME": "django.contrib.auth.password_validation.CommonPasswordValidator"},
    {"NAME": "django.contrib.auth.password_validation.NumericPasswordValidator"},
]

AUTH_USER_MODEL = "accounts.User"
LOGIN_URL = "accounts:login"
LOGIN_REDIRECT_URL = "accounts:profile"
LOGOUT_REDIRECT_URL = "home"

WORKSPACE_INVITATION_EXPIRY_DAYS = int(env("WORKSPACE_INVITATION_EXPIRY_DAYS", "7"))

EMAIL_BACKEND = env(
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.smtp.EmailBackend",
)
EMAIL_HOST = env("DJANGO_EMAIL_HOST", "localhost")
EMAIL_PORT = int(env("DJANGO_EMAIL_PORT", "587"))
EMAIL_HOST_USER = env("DJANGO_EMAIL_HOST_USER", "")
EMAIL_HOST_PASSWORD = env("DJANGO_EMAIL_HOST_PASSWORD", "")
EMAIL_USE_TLS = env_bool("DJANGO_EMAIL_USE_TLS", True, strict=True)
EMAIL_USE_SSL = env_bool("DJANGO_EMAIL_USE_SSL", False, strict=True)
EMAIL_TIMEOUT = float(env("DJANGO_EMAIL_TIMEOUT", "5"))
DEFAULT_FROM_EMAIL = env("DJANGO_DEFAULT_FROM_EMAIL", "TaskFlow <noreply@example.com>")
if not math.isfinite(EMAIL_TIMEOUT) or not 0 < EMAIL_TIMEOUT <= 10:
    raise RuntimeError("DJANGO_EMAIL_TIMEOUT must be greater than zero and at most 10 seconds.")
if EMAIL_USE_TLS and EMAIL_USE_SSL:
    raise RuntimeError("SMTP TLS and SSL are mutually exclusive.")
if not 1 <= EMAIL_PORT <= 65535:
    raise RuntimeError("DJANGO_EMAIL_PORT must be between 1 and 65535.")
if not EMAIL_HOST or any(character.isspace() for character in EMAIL_HOST) or "://" in EMAIL_HOST:
    raise RuntimeError("DJANGO_EMAIL_HOST must be an SMTP hostname.")
if bool(EMAIL_HOST_USER) != bool(EMAIL_HOST_PASSWORD):
    raise RuntimeError("SMTP username and password must be provided together.")
try:
    validate_email(parseaddr(DEFAULT_FROM_EMAIL)[1])
except ValidationError:
    raise RuntimeError("DJANGO_DEFAULT_FROM_EMAIL must be a valid sender address.") from None
if "\r" in DEFAULT_FROM_EMAIL or "\n" in DEFAULT_FROM_EMAIL:
    raise RuntimeError("DJANGO_DEFAULT_FROM_EMAIL must be a valid sender address.")

LANGUAGE_CODE = "fa-ir"
TIME_ZONE = env("DJANGO_TIME_ZONE", "Asia/Tehran")
USE_I18N = True
USE_TZ = True

STATIC_URL = "/static/"
STATIC_ROOT = BASE_DIR / "staticfiles"
STATICFILES_DIRS = [BASE_DIR / "static"]
STORAGES = {
    "default": {
        "BACKEND": "django.core.files.storage.FileSystemStorage",
    },
    "staticfiles": {
        "BACKEND": "whitenoise.storage.CompressedManifestStaticFilesStorage",
    },
}

MEDIA_URL = "media/"
MEDIA_ROOT = BASE_DIR / "media"

DEFAULT_AUTO_FIELD = "django.db.models.BigAutoField"

LOG_LEVEL = env("DJANGO_LOG_LEVEL", "INFO")
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "standard": {
            "format": "{levelname} {asctime} {name} {message}",
            "style": "{",
        }
    },
    "handlers": {
        "console": {
            "class": "logging.StreamHandler",
            "formatter": "standard",
        }
    },
    "root": {"handlers": ["console"], "level": LOG_LEVEL},
    "loggers": {"django": {"handlers": ["console"], "level": LOG_LEVEL, "propagate": False}},
}
