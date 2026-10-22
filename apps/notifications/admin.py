from django.contrib import admin

from apps.boards.admin import ReadOnlyAdminMixin

from .models import Notification


@admin.register(Notification)
class NotificationAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("kind", "recipient", "task", "created_at", "read_at")
    list_select_related = ("recipient", "task")
