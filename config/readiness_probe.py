"""Private readiness subprocess; never print connection or error details."""

import json
import sys

import psycopg


def main():
    database = json.load(sys.stdin)
    try:
        with (
            psycopg.connect(
                dbname=database["NAME"],
                user=database["USER"],
                password=database["PASSWORD"],
                host=database["HOST"],
                port=database["PORT"],
                connect_timeout=2,
                options="-c statement_timeout=2000",
                autocommit=True,
            ) as probe,
            probe.cursor() as cursor,
        ):
            cursor.execute("SELECT 1")
            return 0 if cursor.fetchone() == (1,) else 1
    except psycopg.Error:
        return 1


if __name__ == "__main__":
    sys.exit(main())
