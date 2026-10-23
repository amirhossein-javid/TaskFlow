import json
import subprocess
import sys
from pathlib import Path

from django.conf import settings
from django.db import transaction
from django.http import JsonResponse
from django.views.decorators.http import require_safe


@transaction.non_atomic_requests
@require_safe
def live(request):
    return JsonResponse({"status": "ok"}, headers={"Cache-Control": "no-store"})


@transaction.non_atomic_requests
@require_safe
def ready(request):
    database = settings.DATABASES["default"]
    try:
        # libpq's timeout excludes DNS. A short-lived child bounds the whole probe
        # and is killed/reaped on timeout. Credentials travel over stdin, not argv.
        result = subprocess.run(
            [sys.executable, "-m", "config.readiness_probe"],
            cwd=Path(__file__).resolve().parents[1],
            input=json.dumps(
                {key: database[key] for key in ("NAME", "USER", "PASSWORD", "HOST", "PORT")}
            ).encode(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
        )
        healthy = result.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        healthy = False
    return JsonResponse(
        {"status": "ok" if healthy else "unavailable"},
        status=200 if healthy else 503,
        headers={"Cache-Control": "no-store"},
    )
