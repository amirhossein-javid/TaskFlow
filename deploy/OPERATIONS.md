# Production operations

Run from the repository root. These procedures use the independent production
Compose file, including the localhost/self-signed setup in README. No public host
or external service is required. Python 3.12+ and Docker Compose are needed on the
operator's machine; PostgreSQL client tools run inside the existing db container.
The examples below use a Linux shell:

```sh
dc() { docker compose --env-file .env.production -f compose.production.yaml -p taskflow-production "$@"; }
```

In PowerShell, spell out that Compose prefix instead of defining the shell
function. Python tools use binary subprocess streams directly; do not pipe dump
or archive bytes through PowerShell text redirection.

## Health and logs

- `GET`/`HEAD /health/live/` returns 200 without database access.
- `GET`/`HEAD /health/ready/` returns 200 after a fresh PostgreSQL `SELECT 1`, or
  generic 503. Responses are no-store and disclose no database/error details.
  A short-lived probe has a five-second wall-clock deadline, including DNS;
  libpq's two-second connect timeout alone does not cover DNS. Query timeout is
  two seconds. Credentials reach the probe over stdin, never command arguments.
- Readiness proves connectivity, not migration completion, SMTP delivery, free
  disk space or backup freshness. Run migration and application smoke checks too.
- Docker checks web readiness every 30 seconds, with a six-second HTTP timeout
  and seven-second process timeout. Inspect `dc ps` or run
  `dc exec -T web python deploy/healthcheck.py`. Unhealthy status does not restart
  a container automatically and is not a substitute for operator attention.

```sh
dc logs --tail 100 web nginx db
curl --cacert .runtime/tls/fullchain.pem https://localhost:8443/health/ready/
```

Production application and Gunicorn logs are JSON at INFO level. Safe fields
include time, event, process, method, status, duration and generated request ID.
Exceptions retain their class and up to eight file/function/line locations, never
exception text, source lines, locals, request bodies, URLs, query strings, cookies
or headers. Invitation failures retain only an integer invitation ID. Unrecognized
messages become generic events; malformed records fail closed without dumping
their arguments. Use exception location/type, request ID and status together to
investigate; full payload diagnostics require a controlled local reproduction.
Development logging is unchanged.

Nginx generates and overwrites `X-Request-ID` before proxying. Its JSON request
events include status, upstream status and timings; 5xx responses are `proxy_error`
events. Native Nginx HTTP error messages cannot be custom-formatted and can embed
raw request lines, so they are suppressed. Main-process startup/lifecycle errors
remain available on stderr. Gunicorn request and error events use the same safe
formatter. Keep the trusted proxy boundary intact. PostgreSQL suppresses failing
SQL statements/parameter details; its administrative logs still require restricted
access. Every production service uses Docker `json-file` rotation: 10 MiB per file,
three files per container. Docker logs are transient diagnostics, not an audit log.

The production-like console email backend logs an `email_simulated` event without
message contents or recipients. It still simulates sending; configure SMTP for real
delivery. The development console backend still prints messages for local work.

## Consistent backup

Stop writes for the entire database/media snapshot. The tool refuses to operate
while web or Nginx is running; also stop any manually launched commands or other
writers using these volumes/database. Keep db running. The maintenance window is
intentional: no scheduler, worker, snapshot service or online media reconciliation.

```sh
dc stop nginx web
python3 deploy/backup.py backup .runtime/backups --project taskflow-production
```

The output is a new private `*.backup` directory containing `database.dump` (custom
format), `media.tar.gz`, and a versioned manifest with SHA-256 checksums and source
container image metadata. Only ordinary files/directories are archived; symlinks,
hard links in restored archives, devices and path traversal are rejected. Files
are streamed, not loaded wholesale into host memory. Container-local PostgreSQL
socket access uses `taskflow_app`; no password is put into argv, exported to the
host, or written into the backup metadata. Database contents include sensitive
password hashes, sessions and application data, so treat the entire bundle as a
secret. POSIX bundle directories are 0700 and files 0600; use private Windows ACLs
when running on Windows. Repository-local backups are allowed only under ignored
`.runtime/`, which is also excluded from image builds.

Commands fail nonzero on Docker/client/archive errors or timeouts. Incomplete
directories keep a `.partial` suffix and are never published as completed backups.
Do not resume traffic after an unexplained backup failure. Check service state,
disk space, Docker daemon/client availability and the saved partial artifacts;
the tool deliberately does not print potentially sensitive SQL/client stderr.
Use `--timeout SECONDS` for a larger operation budget when needed (default 300 per
subprocess). The tool neither deletes old backups nor restarts services.

```sh
python3 deploy/backup.py verify .runtime/backups/SET.backup --project taskflow-production
```

Checksum verification detects accidental corruption, not authenticity or restore
compatibility. Only restore trusted bundles. A successful `verify` is explicitly
not a successful restoration test. Keep multiple dated bundles and periodically
perform the isolated restore below, particularly before deleting older backups.

Copy completed bundles to independently controlled storage outside the server,
using authenticated encrypted transfer and encryption at rest, with access limited
to operators. Check the copied checksums and perform restoration from that copy.
Do not keep the only backup on the Docker host or publish it through Nginx. Store
the matching release/image and environment/secrets separately and securely: dumps
exclude PostgreSQL roles/passwords, Django signing secrets, SMTP secrets and TLS
keys. Retain the original signing secret when sessions/signed links must survive;
rotating it invalidates signed state. Choose retention and backup frequency from
the acceptable data-loss window; scheduling and off-host storage are manual here.

## Restore into fresh volumes

Restore refuses any existing user database objects or media content and never
overwrites a populated instance. Use a new, explicit project name to get distinct
volumes. Provision its secrets and the matching source application image first.
Do not run migrations before restoration: the dump includes schema and migration
history. Keep the same PostgreSQL major version (17) for this verified procedure.

```sh
docker compose --env-file .env.production -f compose.production.yaml -p taskflow-restore-check up -d db
docker compose --env-file .env.production -f compose.production.yaml -p taskflow-restore-check run --rm web python manage.py check
python3 deploy/backup.py restore .runtime/backups/SET.backup --project taskflow-restore-check
docker compose --env-file .env.production -f compose.production.yaml -p taskflow-restore-check run --rm web python manage.py migrate --check
docker compose --env-file .env.production -f compose.production.yaml -p taskflow-restore-check up -d web nginx
```

The one-off `check` waits for initial db bootstrap without creating application
tables. The fixed application role/database/schema must match the Compose setup.
Restore verifies checksums and media safety before mutation, restores PostgreSQL
with `--single-transaction --exit-on-error --no-owner --no-acl`, and assigns media
to the non-root application user with 0755 directories and 0644 files. Its `--clean`
is permitted only after the empty-database guard, to recreate the empty public
schema correctly. The original database/media are never a restore target.

Database and media restoration cannot be one cross-resource transaction. A later
media/disk failure can leave the target partially restored: keep it offline,
investigate, and retry using fresh empty volumes. Never claim success from just
the presence of a dump or a healthy database. Verify users, memberships, project/
task relationships, migration history, media contents and application behavior.
When testing on the same machine, stop the source Nginx or use different ports;
Docker project names isolate volumes/networks, not published host ports.

## Repeatable local operations verification

Use fresh disposable projects, local secrets/certificate from README and no real
data. Select unused loopback ports in `.env.production`; pass their HTTPS port to
the scripts when it differs from 8443.

```sh
docker compose --env-file .env.production -f compose.production.yaml -p taskflow-ops-check build web
docker compose --env-file .env.production -f compose.production.yaml -p taskflow-ops-check run --rm web python manage.py migrate --noinput
docker compose --env-file .env.production -f compose.production.yaml -p taskflow-ops-check up -d
python3 deploy/verify_runtime.py --project taskflow-ops-check
python3 deploy/verify_operations.py
```

The second script deliberately stops PostgreSQL, temporarily disables application
role login to exercise a real 500, stops Gunicorn to exercise a proxy 502/504, and checks
logs with secret sentinels. It seeds a workspace/project/task and uses the runtime
check's real user/avatar/session. It then creates a backup, restores into the
distinct fresh `taskflow-restore-check` project, compares complete serialized
database and per-file media digests, checks migration history and readiness.
No live data or infrastructure should ever be passed to this script. Both project
names must end in `-check`. It does not delete volumes automatically. After reviewing
the result, clean up only those disposable projects with their exact Compose prefix
and `down -v`. Preserve bundles needed for later verification privately.

## Release and rollback

1. Build from a reviewed, clean release tree with a unique, never-reused image tag.
   Set non-secret `TASKFLOW_IMAGE=taskflow-production-web:RELEASE_ID` in the operator
   environment or `.env.production`; `dc build web`. Record the immutable image ID
   and retain the matching Compose/Nginx/scripts as a release artifact. Archive
   tracked sources with `git archive` and save the tagged image with `docker image
   save` if rollback must work without a registry. Keep artifacts off the server.
2. Record the currently running image with `dc images web` before replacing it.
   Stop Nginx and web, take a consistent backup, and verify its checksums. Ensure
   sufficient disk space for the old/new images, backup and restored data. Have a
   recently tested restoration procedure and access to the original secrets.
3. Run `dc run --rm web python manage.py check --deploy`, inspect intentional HSTS
   warnings, then `dc run --rm web python manage.py migrate --plan`. Review any
   irreversible/data-destructive or long-locking migrations before proceeding.
4. Run `dc run --rm web python manage.py migrate --noinput` once, with all writers
   stopped. Never migrate in each worker or blindly reverse migrations on failure.
   Run `dc run --rm web python manage.py migrate --check` afterward.
5. Start web with `dc up -d --no-build web`. Require the internal healthcheck to
   succeed before `dc up -d --no-build --force-recreate nginx`; recreating Nginx
   refreshes the upstream container address. Verify external HTTPS readiness,
   authentication, workspace/task reads and representative static/media assets.
   Only then reopen traffic and observe safe error/status logs.

If the schema/data remain compatible, stop Nginx/web, select the retained previous
image via `TASKFLOW_IMAGE` (an immutable local `sha256:...` ID also works with
`--no-build`), and use its matching compatible configuration. Start and verify web,
then recreate Nginx. Do not rebuild or reuse a mutable tag as proof of rollback.
Image rollback does not undo data/schema changes, media writes, emails or secrets.
If compatibility is uncertain or a migration changed/deleted data, restore the
pre-release database **and matching media** into fresh volumes with the prior image
and configuration, verify them offline, then arrange the cutover explicitly.
Restoration loses writes after the backup; obtain an explicit operational decision
before discarding those writes. Keep the failed instance intact for investigation.
Never use `down -v` on persistent environments as a rollback shortcut.
