import logging

from django.core.mail.backends.console import EmailBackend


class SafeConsoleEmailBackend(EmailBackend):
    """Keep production-like console simulation without printing message secrets."""

    def write_message(self, message):
        logging.getLogger("config.email").info(
            "Email simulated; contents omitted", extra={"event": "email_simulated"}
        )
