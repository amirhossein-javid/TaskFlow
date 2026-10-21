from django.contrib import admin

from .models import Board, BoardColumn, Task


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
class TaskAdmin(admin.ModelAdmin):
    list_display = ("title", "column", "priority", "assignee", "due_date")
    list_filter = ("priority", "column__board__project__workspace")
    search_fields = ("title", "description", "column__board__project__name")
