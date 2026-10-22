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

## CBVs and service layer

- Views use Django generic CBVs, `FormView`, or focused custom `View` subclasses.
- Access mixins authenticate users and resolve workspace, project, board, task, and comment scope.
- Views own HTTP handling, form binding, redirects, messages, templates, and JSON contracts.
- Services own business authorization, validation, transactional writes, and ordering changes.
- Do not let `ModelFormMixin` or Admin save service-backed domain mutations directly.
- Call the existing service operation from `form_valid()` or the explicit HTTP handler.
- Keep models responsible for schema constraints and local model validation.
- Add a service only for real domain behavior; do not build generic action frameworks.

## Authentication and authorization

- `accounts.User` authenticates by unique email and has a one-to-one `Profile`.
- Reuse Django authentication, password hashing, CSRF middleware, and safe redirect behavior.
- Workspace roles are Owner, Admin, and Member; use existing permission helpers and mixins.
- Scope nested objects through their parent workspace/project/board in every lookup.
- Return 404 for missing or cross-scope objects and 403 for an in-scope forbidden action.
- Preserve dispatch order: authentication, HTTP-method rejection, object lookup, then permission checks.
- Authenticated unsupported methods must return 405 before scoped-object or role resolution.
- Read-only pages accept GET/HEAD; mutations use POST and require CSRF protection.
- Define `http_method_names` explicitly and preserve existing redirects and `Allow` headers.

## Transactions and concurrency

- PostgreSQL is required; do not add SQLite fallbacks to application or test settings.
- Keep multi-row invariants inside `transaction.atomic()` and use `select_for_update()` as established.
- Workspace owner-safety operations lock the workspace, then all memberships ordered by primary key.
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
- Task, comment, and activity Admin interfaces are intentionally read-only.
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

## Tests and validation

- Place tests beside each app under `apps/<app>/tests/`; add focused regression tests with fixes.
- Run focused tests while iterating and the full suite for substantial or cross-app changes.
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
