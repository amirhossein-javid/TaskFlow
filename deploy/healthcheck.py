"""Internal probe; the private proxy header matches the Nginx trust boundary."""

import http.client
import os
import sys

connection = http.client.HTTPConnection("127.0.0.1", 8000, timeout=6)
try:
    connection.request(
        "GET",
        "/health/ready/",
        headers={
            "Host": os.environ["DJANGO_ALLOWED_HOSTS"].split(",")[0],
            "X-Forwarded-Proto": "https",
        },
    )
    sys.exit(0 if connection.getresponse().status == 200 else 1)
except OSError:
    sys.exit(1)
finally:
    connection.close()
