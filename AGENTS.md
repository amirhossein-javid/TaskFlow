# TaskFlow Codex Instructions

## Scope and working style

- This file applies to the entire repository.
- Inspect the relevant models, services, mixins, views, URLs, templates, and tests before editing.
- Prefer focused, maintainable changes; avoid speculative features and unnecessary abstractions.
- Preserve public URLs, template context keys, response formats, permissions, and transaction boundaries.
- Keep implementation reports and working context concise and evidence-based.
- Write code, identifiers, comments, docstrings, documentation, and commit messages in English.
- Keep all user-facing UI text and validation messages in Persian.

## Stack and layout

- Python 3.12+, Django 5.2, PostgreSQL, Django Templates, vanilla CSS/JavaScript.
- Docker Compose provides `web` and private `db` services; Gunicorn and WhiteNoise serve the app.
- `config/settings/` contains shared, development, and production settings.
- Domain apps live in `apps/accounts`, `apps/workspaces`, `apps/projects`, `apps/boards`, and `apps/notifications`.
- Shared templates are under `templates/`; source static assets are under `static/`.
- Tests use pytest, pytest-django, pytest-cov, and a real PostgreSQL database.
- Development tooling is configured in `pyproject.toml`, `pytest.ini`, and `.pre-commit-config.yaml`.

## Production boundary

- Keep `compose.production.yaml` independent of development Compose. Only Nginx may publish
  ports; preserve private proxy/database networks and the restricted `taskflow_app` role.
- Preserve fail-fast production settings validation, HTTPS-only cookies and encrypted SMTP
  with finite positive socket timeouts. Socket timeouts do not bound DNS or total delivery time.
- Nginx replaces forwarding headers and validates the public Host. Django's proxy SSL header
  is safe only behind that boundary; do not trust client headers for IP-based rate limits.
- Collect manifest static assets at image build time without production secrets or a database.
  Keep runtime secrets/TLS material outside Git and the build context, and media in its volume.
- Never regenerate passwords for an existing database volume as a rotation mechanism;
  coordinate file secrets with database role passwords explicitly.
- Apply avatar decoding, pixel/size limits and pixel-only re-encoding in both profile and Admin
  forms. Preserve existing/cleared uploads and never serve arbitrary media as active documents.
- Production migrations are explicit one-off operations under the application role, not startup
  side effects. Initialization scripts only provision empty PostgreSQL volumes.
- For runtime/proxy changes, run README's disposable HTTPS runtime check in addition to focused
  settings/security tests. Never use its account creation/container recreation against live data.
- Liveness must not query the database; readiness must retain a wall-clock deadline including DNS.
  Keep probe credentials off argv/logs and health responses free of internal details.
- Production logging is allowlisted: do not add raw messages, exception values, SQL, headers,
  URL/query values or email contents to output. Preserve request correlation across Nginx/Django.
- Database/media backups require stopped writers. Restore only into empty isolated targets;
  never overwrite live data or claim verification without an actual restoration and data checks.
  Validate bundle checksums and archive paths/types before database mutation; checksums do not
  establish authenticity. Restore schema and migration history before running migration checks.
  Follow deploy/OPERATIONS.md for explicit release, migration, backup and rollback procedures.

## CBVs and service layer

- Views use Django generic CBVs, `FormView`, or focused custom `View` subclasses.
- Access mixins authenticate users and resolve workspace, project, board, task, and comment scope.
- Views own HTTP handling, form binding, redirects, messages, templates, and JSON contracts.
- Services own business authorization, validation, transactional writes, and ordering changes.
- Do not let `ModelFormMixin` or Admin save service-backed domain mutations directly.
- Workspace, invitation, project, board, and collaboration Admin interfaces, including
  membership and column inlines, are intentionally read-only.
- Call the existing service operation from `form_valid()` or the explicit HTTP handler.
- Keep models responsible for schema constraints and local model validation.
- Add a service only for real domain behavior; do not build generic action frameworks.

## Authentication and authorization

- `accounts.User` authenticates by canonical, case-insensitive email and has a one-to-one `Profile`.
  Reuse `UserManager.normalize_email()` across model, registration, and Admin writes; preserve
  database uniqueness and handle only recognized email constraint conflicts as form errors after rollback.
- Email data migrations must reject canonical identity collisions atomically; never merge or
  delete accounts automatically to satisfy uniqueness.
- Reuse Django authentication, password hashing, CSRF middleware, and safe redirect behavior.
  Preserve validated invitation destinations through login, registration errors, and account switching;
  encode nested query strings without weakening host or HTTPS checks.
- Workspace roles are Owner, Admin, and Member; use existing permission helpers and mixins.
- Scope nested objects through their parent workspace/project/board in every lookup.
- Return 404 for missing or cross-scope objects and 403 for an in-scope forbidden action.
  Workspace update/delete views must also translate `Workspace.DoesNotExist` from service lock
  acquisition into 404 when the workspace disappears after initial lookup.
- Preserve dispatch order: authentication, HTTP-method rejection, object lookup, then permission checks.
- Authenticated unsupported methods must return 405 before scoped-object or role resolution.
- Read-only pages accept GET/HEAD; mutations use POST and require CSRF protection.
- Define `http_method_names` explicitly and preserve existing redirects and `Allow` headers.

## Transactions and concurrency

- PostgreSQL is required; do not add SQLite fallbacks to application or test settings.
- Keep multi-row invariants inside `transaction.atomic()` and use `select_for_update()` as established.
- Workspace owner-safety operations lock the workspace, then all memberships ordered by primary key.
- Workspace settings and deletion revalidate current ownership inside their service transactions;
  deletion also rechecks the current confirmation name. Before locking memberships for deletion,
  lock the workspace's projects by primary key to coordinate with project/board mutations.
- Invitation acceptance locks the accepting User with `select_for_update(no_key=True)` before
  the workspace and invitation. Preserve compatibility with deferred User FK `KEY SHARE` checks.
- Invitation creation/resend commits before synchronous email delivery; keep these HTTP views
  outside request-wide transactions. SMTP must never hold workspace/membership/invitation locks.
  Retain committed invitations after unconfirmed delivery and never automatically retry SMTP.
- Resends lock workspace, current actor membership, then the scoped invitation; revalidate role,
  pending status and current membership. Rotate only the token hash, preserve expiry, and never
  restore an old hash after failure or log raw tokens/SMTP exception contents.
- Admin user deletion locks Users by primary key and checks each one's current memberships before
  acquiring the next User lock. Reject deletion of any member, including in bulk actions; retain
  the locks through deletion so invitation acceptance cannot race the membership check.
- Board mutations lock project, board, actor membership, then affected child rows.
- Keep actor membership locks scoped with `select_for_update(of=("self",))` when joining User.
  Review joined lock targets: unintended User locks conflict with recipient FK `KEY SHARE` checks.
- Board-wide ordering locks columns by primary key before tasks by primary key.
- Comment writes lock the task before the comment; never introduce inverse lock acquisition.
- Preserve dense `(board, position)` and `(column, position)` ordering and their unique constraints.
- Re-read ordering state after locks; do not calculate moves from stale request-time model instances.
- Add PostgreSQL concurrency tests for changes to locking, ordering, or last-owner invariants.
- Concurrency tests use `transaction=True`, separate connections, barriers, and bounded timeouts.
- Cover cross-project reciprocal actors/recipients through commit when testing notification locks;
  deferred FK checks run at commit and same-project serialization can hide deadlocks.
- Keep current-state predicates for conditional read-state updates on the UPDATE target, outside
  authorization subqueries, so PostgreSQL rechecks them after concurrent row-lock waits.

## Tasks, comments, and activity

- Archived projects remain readable but reject every project, board, task, and comment mutation.
- `TaskActivity` is product history, not a tamper-proof security audit log.
- Record meaningful activity in the same service transaction as the corresponding task mutation.
- Do not use signals for core activity recording or log no-op/incidental neighbor position changes.
- Keep event metadata explicit and covered by assertions when event behavior changes.
- Task deletion preserves activity through the nullable task relation and stored task title.
- Comment deletion follows task cascade behavior; deleted users remain representable through nullable actors.
- Create notifications explicitly in the same service transaction as the task change and source
  `TaskActivity`; require active recipients with current task access, exclude self-notifications,
  and preserve recipient/activity uniqueness.
- Use `Notification.objects.visible_to(user)` for inboxes, unread counts, and read-state writes.
  Preserve current task authorization after membership changes; archived projects allow personal
  notification read-state changes without permitting domain mutations.

## Templates and frontend

- The interface is Persian (`fa-IR`), RTL, responsive, and supports light and dark themes.
- Reuse design tokens and shared components from `static/css/main.css` and `templates/base.html`.
- Use self-hosted Vazirmatn for UI text and system monospace for technical identifiers.
- Preserve accessible labels, keyboard controls, focus states, contrast, and reduced-motion behavior.
- Keep JavaScript framework-free and treat server-side authorization as authoritative.
- Include `{% csrf_token %}` in every state-changing form.
- Canceled or failed Kanban drags restore the last known persisted position. Keep recovery state
  past `dragend`, prevent overlapping saves, and refresh server ordering after failed requests
  because a lost response may follow a committed write.

## Tests and validation

- Place tests beside each app under `apps/<app>/tests/`; add focused regression tests with fixes.
- Run focused tests while iterating and the full suite for substantial or cross-app changes.
- For Kanban JavaScript changes, run the Node.js regression tests documented in README's Run tests section.
- The default pytest configuration enforces at least 85% application coverage.
- Full PostgreSQL suite:
  `docker compose run --rm web sh -c "pip install -r requirements/development.txt && pytest"`
- Concurrency suite:
  `docker compose run --rm web sh -c "pip install -r requirements/development.txt && pytest apps -k concurrency --no-cov"`
- Django checks: `python manage.py check`
- Migration drift: `python manage.py makemigrations --check --dry-run`
- Apply committed migrations against PostgreSQL with `python manage.py migrate` when required.
- Quality checks: `ruff check .` and `ruff format --check .`
- Hook validation: `pre-commit run --all-files`
- Never claim a check passed if it was skipped, unavailable, or run against the wrong database.

## Git discipline

- Preserve unrelated and pre-existing working-tree changes; stage only files for the current increment.
- Before committing substantive changes, concisely review the affected diff for correctness,
  permissions, edge cases, transaction safety, and regressions; fix confirmed issues without
  speculative refactoring.
- Local commits are allowed only after successful verification when the user requested implementation.
- Use Conventional Commits such as `feat(boards): ...`, `fix(workspaces): ...`, or `docs: ...`.
- Keep each commit coherent and independently verifiable; do not amend or rewrite existing commits.
- Never push, merge, rebase, reset, amend, deploy, create/delete branches, or switch branches unless
  the user explicitly requests that exact operation.
