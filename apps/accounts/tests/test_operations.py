import io
import json
import logging
import subprocess
import sys
from unittest.mock import patch

import pytest
from django.core.mail import EmailMessage
from django.http import HttpResponse
from django.test import RequestFactory

from config.email import SafeConsoleEmailBackend
from config.logging import RequestLogMiddleware, SafeJSONFormatter


def test_liveness_is_public_safe_and_never_opens_a_database(client):
    with patch("config.health.subprocess.run") as connect:
        assert client.get("/health/live/").json() == {"status": "ok"}
        assert client.head("/health/live/").status_code == 200
        assert client.post("/health/live/").status_code == 405
        connect.assert_not_called()


@pytest.mark.django_db
def test_readiness_checks_real_postgres_and_does_not_cache(client):
    response = client.get("/health/ready/")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert response.headers["Cache-Control"] == "no-store"


def test_readiness_uses_bounded_separate_connection_and_hides_failures(client):
    with patch(
        "config.health.subprocess.run",
        side_effect=subprocess.TimeoutExpired("private-password-hostname", 5),
    ) as connect:
        response = client.get("/health/ready/")
    assert response.status_code == 503
    assert response.json() == {"status": "unavailable"}
    assert b"private" not in response.content
    assert connect.call_args.kwargs["timeout"] == 5
    assert "PASSWORD" not in str(connect.call_args.args)
    assert client.post("/health/ready/").status_code == 405


def test_error_logs_keep_location_type_and_status_without_request_or_exception_data():
    secret = "SENTINEL-password-cookie-authorization-token-query"
    try:
        raise ValueError(secret)
    except ValueError:
        error = sys.exc_info()
    record = logging.LogRecord(
        "django.request", logging.ERROR, __file__, 1, secret, (secret,), error
    )
    record.request = RequestFactory().get(
        f"/workspaces/invitations/{secret}/?password={secret}",
        HTTP_AUTHORIZATION=secret,
        HTTP_COOKIE=secret,
    )
    record.status_code = 500
    result = SafeJSONFormatter().format(record)
    assert secret not in result
    data = json.loads(result)
    assert data["exception"] == "ValueError" and data["status"] == 500
    assert data["frames"][0]["file"] == "test_operations.py"
    assert "frames" in data and "method" in data


def test_gunicorn_access_atoms_and_formatting_failures_never_dump_raw_arguments():
    secret = "SENTINEL-private-header"
    record = logging.LogRecord("gunicorn.access", logging.INFO, __file__, 1, secret, (), None)
    record.args = {
        "s": "403",
        "M": "1.2",
        "m": "POST",
        "{x-request-id}i": "a" * 32,
        "q": secret,
        "{cookie}i": secret,
    }
    result = SafeJSONFormatter().format(record)
    assert secret not in result and json.loads(result)["status"] == 403
    record.args["s"] = secret
    assert SafeJSONFormatter().format(record) == '{"event":"log_encoding_failed"}'


def test_request_logs_ignore_paths_queries_headers_and_keep_safe_correlation(caplog):
    secret = "SENTINEL-private-data"
    request = RequestFactory().post(
        f"/accounts/password/reset/uid/{secret}/?next={secret}",
        {"password": secret},
        HTTP_X_REQUEST_ID=secret,
        HTTP_AUTHORIZATION=secret,
    )
    with caplog.at_level(logging.INFO, logger="config.requests"):
        response = RequestLogMiddleware(lambda request: HttpResponse(status=403))(request)
    record = caplog.records[-1]
    data = json.loads(SafeJSONFormatter().format(record))
    assert data["status"] == 403 and data["method"] == "POST"
    assert data["request_id"] == response.headers["X-Request-ID"]
    assert len(data["request_id"]) == 32 and secret not in json.dumps(data)


def test_production_console_simulates_without_printing_email_contents(caplog):
    stream = io.StringIO()
    backend = SafeConsoleEmailBackend(stream=stream)
    with caplog.at_level(logging.INFO):
        assert (
            backend.send_messages(
                [
                    EmailMessage(
                        "secret subject",
                        "secret token",
                        "from@example.com",
                        ["private@example.com"],
                    )
                ]
            )
            == 1
        )
    assert not stream.getvalue()
    assert "secret" not in caplog.text and "private@example.com" not in caplog.text
