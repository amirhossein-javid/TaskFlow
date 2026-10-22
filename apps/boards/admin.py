from django.contrib import admin

from .models import (
    Board,
    BoardColumn,
    ChecklistItem,
    ProjectLabel,
    Task,
    TaskActivity,
    TaskChecklist,
    TaskComment,
    TaskLabel,
)


class ReadOnlyAdminMixin:
    """Allow inspection while preventing all admin mutation paths."""

    actions = None

    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


class BoardColumnInline(admin.TabularInline):
    model = BoardColumn
    extra = 0
    ordering = ("position",)
    can_delete = False


@admin.register(Board)
class BoardAdmin(admin.ModelAdmin):
    list_display = ("project", "created_at")
    search_fields = ("project__name", "project__workspace__name")
    inlines = (BoardColumnInline,)

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(Task)
class TaskAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("title", "column", "priority", "assignee", "due_date")
    list_filter = ("priority", "column__board__project__workspace")
    search_fields = ("title", "description", "column__board__project__name")


@admin.register(ProjectLabel)
class ProjectLabelAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("name", "project", "color")


@admin.register(TaskLabel)
class TaskLabelAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("task", "label")


@admin.register(TaskChecklist)
class TaskChecklistAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("title", "task", "created_at")


@admin.register(ChecklistItem)
class ChecklistItemAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("text", "checklist", "is_completed")


@admin.register(TaskComment)
class TaskCommentAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("task", "author", "created_at", "updated_at")
    search_fields = ("body", "task__title", "author__email")
    list_filter = ("task__column__board__project__workspace",)


@admin.register(TaskActivity)
class TaskActivityAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("task_title", "event_type", "actor", "project", "created_at")
    list_filter = ("event_type", "project__workspace")
    search_fields = ("task_title", "actor__email", "project__name")
    readonly_fields = (
        "project",
        "task",
        "actor",
        "event_type",
        "task_title",
        "metadata",
        "schema_version",
        "created_at",
    )
