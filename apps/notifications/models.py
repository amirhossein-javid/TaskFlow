from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Notification(models.Model):
    class Kind(models.TextChoices):
        ASSIGNMENT = "assignment", _("وظیفه به شما واگذار شد")
        COMMENT = "comment", _("دیدگاه جدیدی برای وظیفهٔ شما ثبت شد")
        COLUMN_CHANGE = "column_change", _("ستون وظیفهٔ شما تغییر کرد")

    recipient = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("دریافت‌کننده"),
    )
    task = models.ForeignKey(
        "boards.Task",
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("وظیفه"),
    )
    activity = models.ForeignKey(
        "boards.TaskActivity",
        on_delete=models.CASCADE,
        related_name="notifications",
        verbose_name=_("رویداد"),
    )
    kind = models.CharField(_("نوع اعلان"), max_length=20, choices=Kind.choices)
    created_at = models.DateTimeField(_("تاریخ ایجاد"), default=timezone.now)
    read_at = models.DateTimeField(_("تاریخ خواندن"), null=True, blank=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        verbose_name = _("اعلان")
        verbose_name_plural = _("اعلان‌ها")
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "activity"], name="unique_recipient_activity"
            ),
            models.CheckConstraint(
                condition=models.Q(kind__in=["assignment", "comment", "column_change"]),
                name="valid_notification_kind",
            ),
        ]
        indexes = [
            models.Index(fields=["recipient", "-created_at", "-id"], name="notification_inbox_idx"),
            models.Index(
                fields=["recipient", "-created_at", "-id"],
                condition=models.Q(read_at__isnull=True),
                name="notification_unread_idx",
            ),
        ]

    def __str__(self):
        return self.get_kind_display()
