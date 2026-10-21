from django.core.exceptions import ValidationError
from django.db import models
from django.utils.translation import gettext_lazy as _

from apps.projects.models import Project


class Board(models.Model):
    project = models.OneToOneField(
        Project,
        on_delete=models.CASCADE,
        related_name="board",
        verbose_name=_("پروژه"),
    )
    created_at = models.DateTimeField(_("تاریخ ایجاد"), auto_now_add=True)

    class Meta:
        verbose_name = _("برد")
        verbose_name_plural = _("بردها")

    def __str__(self) -> str:
        return f"برد {self.project.name}"


class BoardColumn(models.Model):
    board = models.ForeignKey(
        Board,
        on_delete=models.CASCADE,
        related_name="columns",
        verbose_name=_("برد"),
    )
    name = models.CharField(_("نام"), max_length=100)
    position = models.PositiveIntegerField(_("جایگاه"))
    created_at = models.DateTimeField(_("تاریخ ایجاد"), auto_now_add=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["board", "position"],
                name="unique_column_position_per_board",
            )
        ]
        indexes = [models.Index(fields=["board", "position"], name="board_column_order_idx")]
        verbose_name = _("ستون برد")
        verbose_name_plural = _("ستون‌های برد")

    def __str__(self) -> str:
        return self.name

    def clean(self):
        super().clean()
        if not self.name.strip():
            raise ValidationError({"name": "نام ستون نمی‌تواند خالی باشد."})
