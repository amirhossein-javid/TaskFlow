import logging

from django.core.mail import send_mail

logger = logging.getLogger(__name__)

INVITATION_DELIVERY_WARNING = (
    "ارسال دعوت‌نامه تأیید نشد؛ ممکن است ایمیل ارسال شده باشد. "
    "دعوت ذخیره شده است. برای تلاش مجدد از فهرست اعضا استفاده کنید."
)


def send_invitation_email(*, invitation, workspace_name, accept_url):
    """Send a committed invitation once; a timeout may follow SMTP acceptance."""
    try:
        delivered = send_mail(
            subject=f"دعوت به فضای کاری {''.join(workspace_name.splitlines())}",
            message=(
                f"شما برای پیوستن به فضای کاری «{workspace_name}» دعوت شده‌اید.\n\n"
                "برای مشاهده و پذیرش دعوت از این پیوند استفاده کنید:\n"
                f"{accept_url}\n\n"
                "این پیوند محدود، یک‌بارمصرف و مخصوص همین ایمیل است."
            ),
            from_email=None,
            recipient_list=[invitation.email],
            fail_silently=False,
        )
    except Exception:
        # Backend errors can contain recipients, credentials or message/token data.
        # Neither retries nor SMTP exceptions prove the original message was not sent.
        delivered = 0
    if delivered != 1:
        logger.warning("Invitation email submission unconfirmed (invitation_id=%s)", invitation.pk)
        return False
    return True
