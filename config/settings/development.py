from .base import *  # noqa: F403

DEBUG = True

EMAIL_BACKEND = env(  # noqa: F405
    "DJANGO_EMAIL_BACKEND",
    "django.core.mail.backends.console.EmailBackend",
)
