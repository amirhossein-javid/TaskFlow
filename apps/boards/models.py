from django.conf import settings
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


class Task(models.Model):
    class Priority(models.TextChoices):
        LOW = "low", _("کم")
        MEDIUM = "medium", _("متوسط")
        HIGH = "high", _("زیاد")

    column = models.ForeignKey(
        BoardColumn,
        on_delete=models.PROTECT,
        related_name="tasks",
        verbose_name=_("ستون"),
    )
    title = models.CharField(_("عنوان"), max_length=200)
    description = models.TextField(_("توضیحات"), blank=True)
    priority = models.CharField(
        _("اولویت"),
        max_length=10,
        choices=Priority.choices,
        default=Priority.MEDIUM,
    )
    due_date = models.DateField(_("سررسید"), null=True, blank=True)
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="assigned_tasks",
        verbose_name=_("مسئول"),
    )
    creator = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_tasks",
        verbose_name=_("سازنده"),
    )
    position = models.PositiveIntegerField(_("جایگاه"))
    created_at = models.DateTimeField(_("تاریخ ایجاد"), auto_now_add=True)
    updated_at = models.DateTimeField(_("تاریخ به‌روزرسانی"), auto_now=True)

    class Meta:
        ordering = ["position", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["column", "position"],
                name="unique_task_position_per_column",
            ),
            models.CheckConstraint(
                condition=models.Q(priority__in=["low", "medium", "high"]),
                name="valid_task_priority",
            ),
        ]
        indexes = [
            models.Index(fields=["column", "position"], name="task_column_order_idx"),
            models.Index(fields=["assignee", "due_date"], name="task_assignee_due_idx"),
        ]
        verbose_name = _("وظیفه")
        verbose_name_plural = _("وظیفه‌ها")

    def __str__(self) -> str:
        return self.title

    def clean(self):
        super().clean()
        if not self.title.strip():
            raise ValidationError({"title": "عنوان وظیفه نمی‌تواند خالی باشد."})
        if (
            self.assignee_id
            and not self.column.board.project.workspace.memberships.filter(
                user_id=self.assignee_id
            ).exists()
        ):
            raise ValidationError({"assignee": "مسئول باید عضو همین فضای کاری باشد."})
