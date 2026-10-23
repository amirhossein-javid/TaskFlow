#!/bin/sh
set -eu

# The official entrypoint runs this only for a fresh database volume.
# Use psql's SQL-literal quoting; keep credentials out of command-line arguments.
TASKFLOW_APP_PASSWORD=$(tr -d '\r\n' < "$POSTGRES_APP_PASSWORD_FILE")
export TASKFLOW_APP_PASSWORD
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<'SQL'
\getenv app_password TASKFLOW_APP_PASSWORD
CREATE ROLE taskflow_app LOGIN PASSWORD :'app_password'
    NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS;
ALTER DATABASE taskflow OWNER TO taskflow_app;
ALTER SCHEMA public OWNER TO taskflow_app;
REVOKE ALL ON DATABASE taskflow FROM PUBLIC;
REVOKE CREATE ON SCHEMA public FROM PUBLIC;
SQL
unset TASKFLOW_APP_PASSWORD
