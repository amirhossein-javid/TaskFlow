# TaskFlow

TaskFlow is a team task management application built with Django 5.2, PostgreSQL, Django Templates, and vanilla JavaScript. Features through Phase 8 include email-based authentication, workspaces with role-based access, project Kanban boards, comments and activity history, task search and filtering, project labels, task checklists, and in-app notifications. The responsive Persian RTL interface supports light and dark themes.

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

Workspace, invitation, project, board, and collaboration Admin pages are read-only.
Use the application workflows for domain changes so authorization, ownership,
archival rules, and ordering locks remain enforced. Accounts with workspace
memberships cannot be deleted in Admin, including through bulk deletion; first
end their memberships through the owner-safe application workflows. Accounts
without memberships retain normal Admin deletion and Profile cascade behavior.

Workspace settings revalidate the current owner's role inside a transaction.
Workspace deletion locks the workspace, its projects in primary-key order, then
memberships in primary-key order before cascading. Project locks precede membership
locks to coordinate with board mutations. Invitation acceptance first locks the
accepting User with `NO KEY UPDATE`, then the workspace and invitation. This
serializes account deletion before workspace locks while allowing other writes'
deferred User foreign-key checks to commit. If account deletion commits first,
acceptance rejects the invitation; if acceptance commits first, Admin refuses to
delete the now-member account. The workspace-before-invitation order also
coordinates acceptance with workspace deletion.

## Authentication and profiles

The accounts application provides:

- Email-based registration, login, and logout
- Secure password change and password reset using Django's built-in token system
- Profile editing for full name, biography, and avatar
- Protected account pages and authentication-aware navigation

The main account routes are under `/accounts/`. Development password-reset emails are written to the console by default.

Email identity is case-insensitive. Model saves, registration, and Admin normalize
emails by trimming surrounding whitespace and lowercasing; PostgreSQL also enforces
uniqueness on the normalized value. Login accepts email case differences. Concurrent
registration or Admin email conflicts return a Persian validation error.

Migration `accounts.0006_user_email_identity` normalizes existing emails while
preserving user IDs and relationships. It locks the user table for the duration of
the migration. If existing accounts collide after normalization, it aborts atomically
and reports their user IDs without merging or deleting accounts. Before upgrading,
back up the database and schedule a maintenance window; resolve reported identities
explicitly after verifying account ownership, then rerun `migrate`. Do not delete or
merge accounts automatically. Reversing the migration removes the added constraint
but does not restore the original email casing or whitespace.

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
Board assignee filters fall back to email if a legacy User unexpectedly lacks a Profile.

## Run tests

The test suite uses the PostgreSQL service from Docker Compose and enforces at least 85% application coverage. It covers permissions, filtering, profile lifecycle, labels, checklists, notifications, and PostgreSQL concurrency scenarios, including reciprocal comments across projects and competing read-state updates:

```powershell
docker compose run --rm web sh -c "pip install -r requirements/development.txt && pytest"
```

For direct host development, create a virtual environment, install `requirements/development.txt`, and configure the `POSTGRES_*` variables for a local PostgreSQL instance. Then run:

```powershell
python manage.py migrate
python manage.py runserver
pytest
```

Kanban drag cancellation and failed-save regression tests use Node.js 18+ and its
built-in test runner, without extra npm dependencies:

```powershell
node --test apps/boards/tests/kanban.test.cjs
```

These event-handler tests cover same-column and cross-column cancellation,
rejected/network/non-JSON responses after `dragend`, and overlapping-save prevention.
Failed saves restore the last known persisted position immediately, then refresh
the board because a lost response may follow a committed server write.

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

Invitation destinations survive navigation between login and registration,
registration validation errors, and switching away from an incorrect account.
Redirect targets continue to use Django's host and HTTPS safety checks.

Apply the workspace schema migration after updating:

```powershell
docker compose run --rm web python manage.py migrate
```

## Projects

Every project belongs to one workspace and is visible only to that workspace's members. Owners and Admins can create, edit, archive, and restore projects. Members can view projects and collaborate on their tasks, but cannot change project settings. Archived projects remain readable and must be restored before editing project settings or changing boards, tasks, comments, labels, or checklists.

Project routes are nested below their workspace at `/workspaces/<slug>/projects/`. Apply migrations after updating:

```powershell
docker compose run --rm web python manage.py migrate
```

## Kanban boards and tasks

Each project receives exactly one board with three initial workflow columns. Workspace members can create, edit, assign, move, reorder, and delete tasks. Owners and Admins can also create, rename, reorder, and safely delete empty columns. A column containing tasks cannot be deleted until those tasks are moved.

Tasks have a title, description, priority, optional assignee, and optional due date. Task assignment forms offer active workspace members. Task ordering is serialized with database row locks and maintained as a dense, deterministic sequence. Direct URLs remain workspace- and project-scoped. The board supports drag and drop plus keyboard- and mobile-accessible move controls in its complete, manual-order view.

Board routes are nested below their project at `/workspaces/<slug>/projects/<project_id>/board/`.

### Comments and activity history (Phase 5)

Workspace members can comment on tasks and edit or delete their own comments. Task detail pages show independently paginated comments and activity history, including task creation, edits, assignment changes, moves, and comment changes. Meaningful events are recorded in the same service transaction as the corresponding mutation; no-op edits do not create activity.

Deleting a task removes its comments but retains activity records in the database with the stored task title. Activity is product history, not a tamper-proof security audit log. Task, comment, and activity Admin interfaces are read-only.

### Search, filtering, and sorting (Phase 6)

The board supports case-insensitive substring search across task titles and descriptions. Filters combine with AND and cover column, priority, assignee (including unassigned tasks), and an inclusive due-date range. Assignee options include current workspace members and users still assigned to tasks on the current board, without exposing unrelated users.

Tasks can be sorted within each column by creation date, due date, or priority in either direction. Sorting is deterministic and display-only: it never changes stored task positions or column order. Tasks without a due date appear last in both due-date sort directions; manual ordering remains the default.

Search, filters, and sorting use GET parameters, so the URL preserves the selected state for sharing, refresh, and browser navigation. Invalid filters display Persian validation errors and return no tasks. All columns remain visible, with counts reflecting the displayed results.

Task drag and drop, task move buttons, and column ordering controls are disabled whenever filtering or non-default sorting is active. Clearing the filters restores the complete, manual-order view and its move controls for active projects. Archived boards remain searchable and read-only.

### Project labels and task checklists (Phase 7)

Owners and Admins can create, rename, recolor, and delete project-scoped labels with a fixed color palette and case-insensitive name uniqueness within each project. All workspace roles can attach or detach multiple labels from tasks, using only labels from the task's project. Deleting a shared label removes its assignments without deleting tasks.

Owners, Admins, and Members can collaboratively create, edit, and delete multiple checklists per task and their items, including those created by other members. Items can be marked complete or reopened. Checklists and items retain creation order, with no manual reordering; deleting a checklist also deletes its items. Task detail pages show per-checklist progress, while Kanban cards show labels and completed/total item counts across all of a task's checklists. Archived projects keep this information visible but reject all label, assignment, and checklist changes.

Task activity records explicit label attachment/detachment and checklist or item creation, edits, completion, reopening, and deletion in the same transaction as each change. Repeated requests that leave state unchanged create no activity. Shared-label renames, color changes, and deletion do not generate per-task events, and cascading deletions do not generate extra child events.

Application writes go through scoped services. The database enforces foreign keys, valid colors, nonblank text, and unique label names and task-label pairs. Cross-project assignment is validated by the model and service; direct ORM or SQL writes that bypass services are unsupported. Project label, task-label assignment, checklist, and checklist item Admin interfaces are read-only.

### In-app notifications (Phase 8)

The current assignee receives a notification when another user assigns them a task (including at creation), adds a new comment, or moves the task to a different column. Recipients must be active users with current workspace membership. Self-actions, no-op changes, comment edits, and reordering within a column do not notify. Notifications are recorded in the same transaction as the task change and its activity event, with at most one notification per recipient/activity pair.

The inbox at `/notifications/` shows the newest notifications first, with 20 per page and an unread-only filter. Users can mark individual notifications read or unread, or mark all visible notifications read. These operations use CSRF-protected POST requests and are idempotent; opening the inbox or a task does not mark notifications read. The navigation bell refreshes its unread count when a page loads or is refreshed; there is no polling, live delivery, or notification email.

The inbox, unread count, and read-state operations are scoped to the recipient and current task access. Task links use the existing permission checks. Leaving a workspace hides its notifications; rejoining makes retained notifications accessible again. Archived projects remain readable, including notification read-state controls.

Deleting a task, project, or recipient removes the corresponding notifications. There is no automatic retention policy. Notification Admin is read-only.

## Language conventions

- Technical documentation, code comments, docstrings, identifiers, and commit-related descriptions are written in English.
- The user interface uses Persian (`fa-IR`) with right-to-left layout.
- User-facing labels, validation errors, and notifications are written in Persian.
- Database schema and internal code identifiers remain in English.
