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

Production requires strong Django and database secrets, an explicit database name,
host and application role, and explicit allowed hosts. Use exactly one of
`DJANGO_SECRET_KEY` / `DJANGO_SECRET_KEY_FILE` and `POSTGRES_PASSWORD` /
`POSTGRES_PASSWORD_FILE`. Empty, short and obviously weak secrets, wildcard hosts,
unsafe CSRF origins, debug mode and disabled HTTPS redirects fail at startup.
Never commit secrets or `.env` files.

### Production runtime on one host

`compose.production.yaml` is independent of the development Compose file. It runs
Nginx, non-root Gunicorn/Django, and PostgreSQL. Only Nginx publishes ports; its
default bindings are loopback HTTP 8080 and HTTPS 8443. Django and PostgreSQL have
no host ports. The private proxy and database networks are internal; separate
edge and outbound networks provide Nginx ingress and Django email egress.
Do not attach untrusted containers, publish Gunicorn, or place another proxy/CDN
in front without reviewing the trust and client-IP/rate-limit configuration.

Configure Compose through `.env.production` (see `.env.production.example`):

| Variable | Purpose / default |
| --- | --- |
| `TASKFLOW_HOST` | Public hostname or IPv4 address; `localhost` for local checks |
| `TASKFLOW_BIND_ADDRESS` | Host interface for Nginx ports; `127.0.0.1` |
| `TASKFLOW_HTTP_PORT` / `TASKFLOW_HTTPS_PORT` | Published ports; `8080` / `8443` |
| `TASKFLOW_IMAGE` | Application image; use a unique release tag for updates |
| `TASKFLOW_SECRET_DIRECTORY` | Directory containing the three generated secret files; `./.runtime/secrets` |
| `TASKFLOW_TLS_DIRECTORY` | Directory containing `fullchain.pem` and `privkey.pem`; `./.runtime/tls` |

Compose derives Django's allowed host and trusted CSRF origin from the host/HTTPS
port, and fixes the internal database settings. Only variables explicitly forwarded
in `compose.production.yaml` reach Django; adding another setting to the env file
alone does not configure the container. SMTP variables are listed below; protect
the env file if it contains SMTP credentials.

Initial local verification needs Docker Compose, Python 3.12+, and OpenSSL, but no
server purchase, domain or public certificate. Run from the repository root:

```sh
cp .env.production.example .env.production
python3 deploy/prepare_secrets.py
mkdir -p .runtime/tls
chmod 700 .runtime/tls
openssl req -x509 -newkey rsa:2048 -nodes -days 7 \
  -keyout .runtime/tls/privkey.pem -out .runtime/tls/fullchain.pem \
  -subj '/CN=localhost' -addext 'subjectAltName=DNS:localhost'
chmod 600 .runtime/tls/privkey.pem
docker compose --env-file .env.production -f compose.production.yaml build web
docker compose --env-file .env.production -f compose.production.yaml run --rm web python manage.py check --deploy
docker compose --env-file .env.production -f compose.production.yaml run --rm web python manage.py migrate --noinput
docker compose --env-file .env.production -f compose.production.yaml up -d
```

Open `https://localhost:8443`. The self-signed certificate is for local tests;
trust it explicitly in a test client rather than disabling production HTTPS.
For PowerShell, use `Copy-Item` and `New-Item -ItemType Directory` for the first
file/directory commands; protect runtime directories with Windows ACLs instead
of `chmod`. Change the port values in `.env.production` if they are occupied.

The secret generator never overwrites existing credentials. Compose file secrets
are read-only bind mounts, not an encrypted secret store; uid/gid/mode remapping
is not supported for these files. Secret files are readable by the non-root
container, with a host directory of mode 0700 (or equivalent private Windows ACLs).
Keep `.runtime` private; it is excluded from Git and the Docker build context.
Do not regenerate passwords for an existing database volume: changing a file does
not change the database role password. Coordinate credential rotation explicitly.

Fresh database initialization creates `taskflow_app`, which owns the `taskflow`
database and public schema so it can run migrations. It has no superuser,
createdb, createrole, replication or bypass-RLS privileges. Only the database
container receives the bootstrap administrator secret. Initialization scripts run
once on an empty volume; existing/imported databases need their roles, ownership
and privileges provisioned explicitly. Never reuse the development database volume.

Migrations run as an explicit one-off operation, never from each Gunicorn worker
or automatic container startup. For updates, retain the previous image and take
a verified database/media backup first. Stop writes before incompatible migrations,
run checks and migrations once, then recreate **both** web and Nginx (Nginx resolves
the web container address at startup). Verify the new instance before reopening
traffic. Replacing an image does not reverse a schema/data migration; assess
migration reversibility and use a coordinated restore when necessary. Do not use
`down -v` on persistent environments.

Static assets are collected with manifest storage during the image build without
runtime secrets or a database connection. WhiteNoise serves hashed, compressed
assets through Nginx. The named `media` volume survives container replacement;
Django writes it and Nginx mounts it read-only. Only JPEG/PNG/WebP avatar paths are
served, with nosniff, no directory listing, and restrictive content policy. Avatars
are public images, not private workspace attachments. New uploads through profile
and Admin forms must decode as a supported still image, fit a 2 MiB input/output
budget and 16,777,216-pixel limit, and are re-encoded to a random PNG filename with
metadata and appended content removed. Existing images are not automatically
rewritten; inspect legacy uploads before importing an existing media directory.

Nginx replaces Host and forwarding headers, rejects unknown hosts, redirects HTTP
to the configured HTTPS authority, and uses the TCP peer for rate limits.
Gunicorn does not interpret client forwarding headers; Django trusts the isolated
Nginx boundary. HTTPS-only session/CSRF cookies, nosniff, frame protection and
same-origin referrer policy are enabled. HSTS starts at one hour, without preload
or includeSubDomains; increase it only after validating real HTTPS operation.
Login/Admin login share 10 requests/minute with burst 5. Registration, password
reset requests and invitation sending share 3/minute with burst 2. Invitation and
reset-token paths share 30/minute with burst 10. Limits are per client IP, including
users behind the same NAT; tune the explicit zones if normal traffic requires it.
Excess requests receive a static Persian 429 page, `Retry-After: 60`, and no-store.
Ordinary browsing is not limited. Production request/error logs use safe JSON
fields and omit URLs, query strings, cookies, headers and exception contents;
Docker log rotation bounds local storage. See the operations guide below.

For an eventual public host, set `TASKFLOW_HOST` to its DNS name or IPv4 address,
bind Nginx explicitly to the intended host interface, set HTTP/HTTPS ports to
80/443, and supply a valid certificate chain/key in the configured TLS directory.
Arrange certificate renewal and reload Nginx after replacing certificates.
The sample console email backend is only for local verification. Production-like
settings simulate it without printing contents/tokens; development still prints
messages. Configure real delivery before public use.

`GET`/`HEAD /health/live/` checks liveness without database access;
`/health/ready/` checks PostgreSQL within a five-second deadline and returns generic
503 on failure. Docker checks readiness, but an unhealthy status alone does not
restart the container or prove that migrations are complete.

Use [the production operations guide](deploy/OPERATIONS.md) for health/log commands,
`deploy/backup.py` backup, verify and fresh-target restore procedures, disposable
restoration checks, and release/rollback steps. A checksum check is not a restoration
test, and image rollback does not reverse database or media changes. Backups and
off-host copying remain explicit operator actions.

The repeatable runtime check creates an account, recreates containers, and tests
TLS verification, proxy spoofing, CSRF/cookies, manifest assets, avatar persistence,
rate limits and restricted database-role DDL. Use a separate disposable project:

```sh
docker compose --env-file .env.production -f compose.production.yaml -p taskflow-runtime-check build web
docker compose --env-file .env.production -f compose.production.yaml -p taskflow-runtime-check run --rm web python manage.py migrate --noinput
docker compose --env-file .env.production -f compose.production.yaml -p taskflow-runtime-check up -d
python3 deploy/verify_runtime.py
docker compose --env-file .env.production -f compose.production.yaml -p taskflow-runtime-check down -v
```

Pass `--http-port` / `--https-port` to the check script when using different ports.
Do not run these disposable checks against a live environment or while another
stack uses the same published ports. The ordinary pytest suite continues to use
the development database role, because creating a test database requires CREATEDB.

Production email delivery uses Django's SMTP backend by default. Configure these environment variables for the target mail provider:

- `DJANGO_EMAIL_HOST`
- `DJANGO_EMAIL_PORT`
- `DJANGO_EMAIL_TIMEOUT` (default 5 seconds; greater than zero and at most 10)
- `DJANGO_EMAIL_HOST_USER`
- `DJANGO_EMAIL_HOST_PASSWORD`
- `DJANGO_EMAIL_USE_TLS`
- `DJANGO_EMAIL_USE_SSL`
- `DJANGO_DEFAULT_FROM_EMAIL`

Set `DJANGO_EMAIL_BACKEND` only when a different Django email backend is required.
TLS and implicit SSL are mutually exclusive; production SMTP requires one of them.
SMTP host, port, sender and credential pairs are validated at startup. A timeout
must be finite and positive; invalid boolean values fail instead of silently
disabling encryption. `EMAIL_TIMEOUT` bounds individual socket operations, not the
entire request or DNS lookup. Delivery remains synchronous without a worker queue.
The provider accepting a message does not guarantee inbox delivery.

Password reset retains Django's active-account/password checks, token generation,
single-use behavior and generic redirect for existing, unknown, inactive and
unusable-password accounts, including SMTP failures. The completion page makes no
delivery guarantee and never exposes backend errors or account existence. As with
Django's synchronous reset flow, SMTP latency can still produce timing differences.

## Workspaces and invitations

Authenticated users can create multiple workspaces under `/workspaces/`. Workspace access is controlled by Owner, Admin, and Member roles. Owners manage roles and workspace settings, while Owners and Admins can invite and remove eligible members.

Invitation links are single-use, expire after seven days by default, and can only be accepted by a signed-in account with the invited email address. Set `WORKSPACE_INVITATION_EXPIRY_DAYS` to change the lifetime. Email delivery reuses the `DJANGO_EMAIL_*` configuration described above; development writes invitations to the console.

Invitation creation commits before SMTP starts, releasing workspace and membership
locks. These views explicitly opt out of request-wide transactions. A zero send
count, rejected message, connection failure or timeout shows an unconfirmed-delivery
message; it never rolls back the committed invitation or claims success. SMTP may
have accepted DATA before its reply was lost, so the link remains usable. A process
interruption between commit and sending can likewise leave a pending invitation.
There is no automatic retry, durable email queue or exactly-once delivery claim.

Owners can resend pending Member/Admin invitations from the members page; Admins
can resend only Member invitations. The POST-only, CSRF-protected action rechecks
current permissions and pending status under workspace/actor/invitation locks.
Each resend invalidates the old link by rotating its hash; raw tokens are never
stored. Role, recipient, original inviter and expiry remain unchanged. Accepted,
revoked, expired invitations and invitations to current members cannot be resent.
After failure, use this action again; it generates another new link and never
restores a previous token. Concurrent resends can produce multiple emails, but only
the latest committed token is valid. Production Nginx applies the same email rate
limit to creation and resend. Invitation failure logs contain only the invitation
ID, without raw SMTP errors, email addresses or links.

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
