import ipaddress
import re
from pathlib import Path
from urllib.parse import urlsplit

from .base import *  # noqa: F403
from .base import DATABASES, env, env_list


def secret(name, minimum_length):
    value = env(name, "")
    filename = env(f"{name}_FILE", "")
    if bool(value) == bool(filename):
        raise RuntimeError(f"Set exactly one of {name} or {name}_FILE.")
    if filename:
        value = Path(filename).read_text().rstrip("\r\n")
    if len(value) < minimum_length or len(set(value)) < 5 or value.startswith("django-insecure-"):
        raise RuntimeError(f"{name} must be a strong, randomly generated secret.")
    return value


def exact_host(value):
    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return bool(
            len(value) <= 253
            and all(
                re.fullmatch(r"[a-zA-Z0-9](?:[a-zA-Z0-9-]{0,61}[a-zA-Z0-9])?", label)
                for label in value.split(".")
            )
        )


SECRET_KEY = secret("DJANGO_SECRET_KEY", 50)
if env("DJANGO_DEBUG", "false").lower() not in {"false", "0"}:
    raise RuntimeError("DJANGO_DEBUG must be false in production.")
if env("DJANGO_SECURE_SSL_REDIRECT", "true").lower() not in {"true", "1"}:
    raise RuntimeError("HTTPS redirects cannot be disabled in production.")

ALLOWED_HOSTS = env_list("DJANGO_ALLOWED_HOSTS")
if not ALLOWED_HOSTS or not all(exact_host(host) for host in ALLOWED_HOSTS):
    raise RuntimeError("DJANGO_ALLOWED_HOSTS must contain explicit hostnames or IP addresses.")

CSRF_TRUSTED_ORIGINS = env_list("DJANGO_CSRF_TRUSTED_ORIGINS")
for origin in CSRF_TRUSTED_ORIGINS:
    parsed = urlsplit(origin)
    if (
        parsed.scheme != "https"
        or parsed.hostname not in ALLOWED_HOSTS
        or parsed.username
        or parsed.password
        or parsed.path
        or parsed.query
        or parsed.fragment
    ):
        raise RuntimeError("CSRF trusted origins must be HTTPS origins on allowed hosts.")
    try:
        _ = parsed.port
    except ValueError as error:
        raise RuntimeError("Invalid CSRF origin port.") from error

DATABASES["default"].update(
    NAME=env("POSTGRES_DB"),
    USER=env("POSTGRES_USER"),
    HOST=env("POSTGRES_HOST"),
    PASSWORD=secret("POSTGRES_PASSWORD", 32),
)
if not all(DATABASES["default"][key].strip() for key in ("NAME", "USER", "HOST")):
    raise RuntimeError("Production database name, user and host must not be empty.")
if DATABASES["default"]["USER"] in {"postgres", "taskflow"}:
    raise RuntimeError("Use a dedicated application database role, not the bootstrap role.")

DEBUG = False
SECURE_SSL_REDIRECT = True
SESSION_COOKIE_SECURE = True
CSRF_COOKIE_SECURE = True
# Start conservatively; increase only after verifying certificates and HTTPS operation.
SECURE_HSTS_SECONDS = int(env("DJANGO_SECURE_HSTS_SECONDS", "3600"))
if SECURE_HSTS_SECONDS < 0:
    raise RuntimeError("DJANGO_SECURE_HSTS_SECONDS cannot be negative.")
SECURE_HSTS_INCLUDE_SUBDOMAINS = False
SECURE_HSTS_PRELOAD = False
SECURE_CONTENT_TYPE_NOSNIFF = True
SECURE_REFERRER_POLICY = "same-origin"
# Only the isolated Nginx network may reach Gunicorn; Nginx replaces this header.
SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
USE_X_FORWARDED_HOST = False
MEDIA_URL = "/media/"
FILE_UPLOAD_PERMISSIONS = 0o644
FILE_UPLOAD_DIRECTORY_PERMISSIONS = 0o755
DATA_UPLOAD_MAX_MEMORY_SIZE = 3 * 1024 * 1024
