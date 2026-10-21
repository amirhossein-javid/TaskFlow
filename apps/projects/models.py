from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.workspaces.models import Workspace


class Project(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "active", _("فعال")
        ARCHIVED = "archived", _("بایگانی‌شده")

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="projects",
        verbose_name=_("فضای کاری"),
    )
    name = models.CharField(_("نام"), max_length=160)
    description = models.TextField(_("توضیحات"), blank=True)
    status = models.CharField(
        _("وضعیت"),
        max_length=10,
        choices=Status.choices,
        default=Status.ACTIVE,
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_projects",
        verbose_name=_("سازنده"),
    )
    created_at = models.DateTimeField(_("تاریخ ایجاد"), auto_now_add=True)
    updated_at = models.DateTimeField(_("تاریخ به‌روزرسانی"), auto_now=True)

    class Meta:
        ordering = ["-updated_at", "-id"]
        indexes = [
            models.Index(
                fields=["workspace", "status", "-updated_at"],
                name="project_ws_status_updated_idx",
            )
        ]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(status__in=["active", "archived"]),
                name="valid_project_status",
            )
        ]
        verbose_name = _("پروژه")
        verbose_name_plural = _("پروژه‌ها")

    def __str__(self) -> str:
        return self.name

    def clean(self):
        super().clean()
        if not self.name.strip():
            raise ValidationError({"name": "نام پروژه نمی‌تواند خالی باشد."})
