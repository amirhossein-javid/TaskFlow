# TaskFlow

TaskFlow is a team task management application built with Django 5.2 and PostgreSQL. It currently provides email-based authentication, user profiles, workspace membership management, workspace-scoped projects, and Kanban task boards.

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

Standard individual user-creation paths (registration, Admin, `create_user()`,
`create_superuser()`, `createsuperuser`, and normal model saves) create exactly one
Profile through the existing `post_save` signal. The one-to-one constraint prevents
duplicate profiles. Profile deletion is blocked for direct instance and QuerySet
deletes and in Admin; deleting the owning User still cascades to its Profile.
An existing Profile's owner cannot be reassigned in Admin.

Repair missing profiles in an existing database with:

```powershell
docker compose run --rm web python manage.py repair_profiles
```

The command is idempotent, locks each User while repairing it, and leaves all valid
Profiles unchanged, including names, biographies, avatars, and creation dates.
It is safe to rerun after an interruption.

Django's `bulk_create()` bypasses model saves and signals. Importers that use it
must explicitly create the corresponding Profiles, preferably in the same
transaction. Raw fixture loads also skip automatic profile creation. Use
`repair_profiles` after legacy imports when needed. Direct SQL and low-level
operations that bypass these application safeguards remain the caller's
responsibility; there is no database-level guarantee that every User has a Profile.

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

## Workspaces and invitations

Authenticated users can create multiple workspaces under `/workspaces/`. Workspace access is controlled by Owner, Admin, and Member roles. Owners manage roles and workspace settings, while Owners and Admins can invite and remove eligible members.

Invitation links are single-use, expire after seven days by default, and can only be accepted by a signed-in account with the invited email address. Set `WORKSPACE_INVITATION_EXPIRY_DAYS` to change the lifetime. Email delivery reuses the `DJANGO_EMAIL_*` configuration described above; development writes invitations to the console.

Apply the workspace schema migration after updating:

```powershell
docker compose run --rm web python manage.py migrate
```

## Projects

Every project belongs to one workspace and is visible only to that workspace's members. Owners and Admins can create, edit, archive, and restore projects. Members have read-only access. Archived projects remain available for reference and must be restored before they can be edited.

Project routes are nested below their workspace at `/workspaces/<slug>/projects/`. Apply migrations after updating:

```powershell
docker compose run --rm web python manage.py migrate
```

## Kanban boards and tasks

Each project receives exactly one board with three initial workflow columns. Workspace members can create, edit, assign, move, reorder, and delete tasks. Owners and Admins can also create, rename, reorder, and safely delete empty columns. A column containing tasks cannot be deleted until those tasks are moved.

Task ordering is serialized with database row locks and maintained as a dense, deterministic sequence. Assignees must be members of the same workspace, direct URLs remain workspace-scoped, and archived projects expose their board in read-only mode. The responsive Persian interface supports drag and drop plus keyboard- and mobile-accessible move controls.

Board routes are nested below their project at `/workspaces/<slug>/projects/<project_id>/board/`.

## Language conventions

- Technical documentation, code comments, docstrings, identifiers, and commit-related descriptions are written in English.
- The user interface uses Persian (`fa-IR`) with right-to-left layout.
- User-facing labels, validation errors, and notifications are written in Persian.
- Database schema and internal code identifiers remain in English.
