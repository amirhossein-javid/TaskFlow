from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone
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
        on_delete=models.CASCADE,
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


class TaskComment(models.Model):
    task = models.ForeignKey(
        Task,
        on_delete=models.CASCADE,
        related_name="comments",
        verbose_name=_("وظیفه"),
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="task_comments",
        verbose_name=_("نویسنده"),
    )
    body = models.TextField(_("متن دیدگاه"), max_length=5000)
    created_at = models.DateTimeField(_("تاریخ ایجاد"), auto_now_add=True)
    updated_at = models.DateTimeField(_("تاریخ به‌روزرسانی"), auto_now=True)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["task", "-created_at", "-id"],
                name="comment_task_recent_idx",
            )
        ]
        verbose_name = _("دیدگاه وظیفه")
        verbose_name_plural = _("دیدگاه‌های وظیفه")

    def __str__(self) -> str:
        return self.body[:80]

    def clean(self):
        super().clean()
        if not self.body.strip():
            raise ValidationError({"body": "متن دیدگاه نمی‌تواند خالی باشد."})


class TaskActivity(models.Model):
    class EventType(models.TextChoices):
        TASK_CREATED = "task_created", _("وظیفه ساخته شد")
        TASK_UPDATED = "task_updated", _("وظیفه به‌روزرسانی شد")
        ASSIGNEE_CHANGED = "assignee_changed", _("مسئول وظیفه تغییر کرد")
        TASK_MOVED = "task_moved", _("وظیفه جابه‌جا شد")
        COMMENT_CREATED = "comment_created", _("دیدگاه ثبت شد")
        COMMENT_EDITED = "comment_edited", _("دیدگاه ویرایش شد")
        COMMENT_DELETED = "comment_deleted", _("دیدگاه حذف شد")
        TASK_DELETED = "task_deleted", _("وظیفه حذف شد")

    project = models.ForeignKey(
        Project,
        on_delete=models.CASCADE,
        related_name="task_activities",
        verbose_name=_("پروژه"),
    )
    task = models.ForeignKey(
        Task,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="activities",
        verbose_name=_("وظیفه"),
    )
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="task_activities",
        verbose_name=_("انجام‌دهنده"),
    )
    event_type = models.CharField(_("نوع رویداد"), max_length=32, choices=EventType.choices)
    task_title = models.CharField(_("عنوان وظیفه"), max_length=200)
    metadata = models.JSONField(_("جزئیات"), default=dict, blank=True)
    schema_version = models.PositiveSmallIntegerField(_("نسخه ساختار"), default=1)
    created_at = models.DateTimeField(_("تاریخ رویداد"), default=timezone.now)

    class Meta:
        ordering = ["-created_at", "-id"]
        indexes = [
            models.Index(
                fields=["task", "-created_at", "-id"],
                name="activity_task_recent_idx",
            ),
            models.Index(
                fields=["project", "-created_at", "-id"],
                name="activity_project_recent_idx",
            ),
        ]
        verbose_name = _("رویداد وظیفه")
        verbose_name_plural = _("رویدادهای وظیفه")

    def __str__(self) -> str:
        return f"{self.get_event_type_display()}: {self.task_title}"
