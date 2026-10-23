"""Production logs use an allowlist; never format arbitrary messages or exceptions."""

import json
import logging
import re
import time
import traceback
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

METHODS = {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS", "CONNECT", "TRACE"}
EVENTS = {"http_request", "invitation_email_unconfirmed", "email_simulated"}


class SafeJSONFormatter(logging.Formatter):
    def format(self, record):
        try:
            return self.format_safe(record)
        except Exception:
            # logging's default formatting-error handler prints the original
            # message/arguments. Fail closed instead, including malformed atoms.
            return '{"event":"log_encoding_failed"}'

    def format_safe(self, record):
        name = (
            record.name
            if record.name.startswith(("apps.", "config.", "django", "gunicorn"))
            else "application"
        )
        event = getattr(record, "event", "application_log")
        if event not in EVENTS:
            event = "application_error" if record.levelno >= logging.ERROR else "application_log"
        if record.name == "gunicorn.access":
            event = "gunicorn_request"
        elif record.name == "gunicorn.error":
            event = {
                "WORKER TIMEOUT (pid:%s)": "worker_timeout",
                "Booting worker with pid: %s": "worker_start",
                "Worker exiting (pid: %s)": "worker_exit",
            }.get(
                record.msg,
                "gunicorn_error" if record.levelno >= logging.ERROR else "gunicorn_lifecycle",
            )
        data = {
            "time": datetime.fromtimestamp(record.created, UTC).isoformat(),
            "level": logging.getLevelName(record.levelno),
            "logger": name,
            "event": event,
            "pid": record.process,
        }
        request = getattr(record, "request", None)
        method = getattr(record, "method", None) or getattr(request, "method", None)
        status = getattr(record, "status_code", None)
        request_id = getattr(record, "request_id", None) or getattr(request, "request_id", None)
        if record.name == "gunicorn.access" and isinstance(record.args, dict):
            method = record.args.get("m")
            status = int(record.args["s"])
            request_id = record.args.get("{x-request-id}i")
            data["duration_ms"] = float(record.args["M"])
        if method in METHODS:
            data["method"] = method
        if isinstance(status, int) and 100 <= status <= 599:
            data["status"] = status
        if isinstance(request_id, str) and re.fullmatch(r"[0-9a-f]{32}", request_id):
            data["request_id"] = request_id
        if isinstance(getattr(record, "duration_ms", None), (int, float)):
            data["duration_ms"] = record.duration_ms
        if isinstance(getattr(record, "invitation_id", None), int):
            data["invitation_id"] = record.invitation_id
        if record.exc_info:
            data["exception"] = record.exc_info[0].__name__
            data["frames"] = [
                {"file": Path(frame.filename).name, "line": frame.lineno, "function": frame.name}
                for frame in traceback.extract_tb(record.exc_info[2])[-8:]
            ]
        return json.dumps(data, ensure_ascii=True)


def production_logging():
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {"safe": {"()": "config.logging.SafeJSONFormatter"}},
        "handlers": {"console": {"class": "logging.StreamHandler", "formatter": "safe"}},
        "root": {"handlers": ["console"], "level": "INFO"},
        "loggers": {
            name: {"handlers": ["console"], "level": "INFO", "propagate": False}
            for name in ("django", "django.server", "gunicorn.error", "gunicorn.access")
        },
    }


class RequestLogMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        candidate = request.headers.get("X-Request-ID", "")
        request.request_id = candidate if re.fullmatch(r"[0-9a-f]{32}", candidate) else uuid4().hex
        started = time.monotonic()
        response = self.get_response(request)
        response.headers["X-Request-ID"] = request.request_id
        logging.getLogger("config.requests").info(
            "HTTP request completed",
            extra={
                "event": "http_request",
                "method": request.method,
                "status_code": response.status_code,
                "request_id": request.request_id,
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            },
        )
        return response
