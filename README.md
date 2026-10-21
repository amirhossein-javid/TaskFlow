# TaskFlow

TaskFlow is a team task management application built with Django 5.2 and PostgreSQL. It currently provides email-based authentication, user profiles, and workspace membership management.

## Requirements

- Docker and Docker Compose
- Alternatively, Python 3.12+ and an accessible PostgreSQL instance for local development

## Docker setup

Copy the example environment file and replace all placeholder secrets:

```powershell
Copy-Item .env.example .env
docker compose build
docker compose run --rm web python manage.py migrate
docker compose up -d
```

The application is available at `http://localhost:8000`. PostgreSQL is intentionally not exposed to the host.
If port 8000 is already in use, change `WEB_PORT` in `.env`.

## Create a superuser

```powershell
docker compose run --rm web python manage.py createsuperuser
```

The Django Admin is available at `http://localhost:8000/admin/`.

## Authentication and profiles

The accounts application provides:

- Email-based registration, login, and logout
- Secure password change and password reset using Django's built-in token system
- Profile editing for full name, biography, and avatar
- Protected account pages and authentication-aware navigation

The main account routes are under `/accounts/`. Development password-reset emails are written to the console by default.

## Run tests

The test suite uses the PostgreSQL service from Docker Compose:

```powershell
docker compose run --rm web sh -c "pip install -r requirements/development.txt && pytest"
```

For direct host development, create a virtual environment, install `requirements/development.txt`, and configure the `POSTGRES_*` variables for a local PostgreSQL instance. Then run:

```powershell
python manage.py migrate
python manage.py runserver
pytest
```

## Code quality

Run Ruff after installing the development dependencies:

```powershell
ruff check .
ruff format --check .
```

Install and run all pre-commit hooks with:

```powershell
pre-commit install
pre-commit run --all-files
```

## Settings

- Development: `config.settings.development`
- Production: `config.settings.production`

Production requires at least `DJANGO_SECRET_KEY` and `DJANGO_ALLOWED_HOSTS`. Never commit `.env` files. Configure TLS, `CSRF_TRUSTED_ORIGINS`, and allowed hosts for the target environment before deployment.

Production email delivery uses Django's SMTP backend by default. Configure these environment variables for the target mail provider:

- `DJANGO_EMAIL_HOST`
- `DJANGO_EMAIL_PORT`
- `DJANGO_EMAIL_HOST_USER`
- `DJANGO_EMAIL_HOST_PASSWORD`
- `DJANGO_EMAIL_USE_TLS`
- `DJANGO_EMAIL_USE_SSL`
- `DJANGO_DEFAULT_FROM_EMAIL`

Set `DJANGO_EMAIL_BACKEND` only when a different Django email backend is required.

Standard Django user-creation paths automatically create the related Profile. Django does not emit model signals for `bulk_create()`, so callers that use it must create the corresponding profiles explicitly in bulk.

## Workspaces and invitations

Authenticated users can create multiple workspaces under `/workspaces/`. Workspace access is controlled by Owner, Admin, and Member roles. Owners manage roles and workspace settings, while Owners and Admins can invite and remove eligible members.

Invitation links are single-use, expire after seven days by default, and can only be accepted by a signed-in account with the invited email address. Set `WORKSPACE_INVITATION_EXPIRY_DAYS` to change the lifetime. Email delivery reuses the `DJANGO_EMAIL_*` configuration described above; development writes invitations to the console.

Apply the workspace schema migration after updating:

```powershell
docker compose run --rm web python manage.py migrate
```

## Language conventions

- Technical documentation, code comments, docstrings, identifiers, and commit-related descriptions are written in English.
- The user interface uses Persian (`fa-IR`) with right-to-left layout.
- User-facing labels, validation errors, and notifications are written in Persian.
- Database schema and internal code identifiers remain in English.
