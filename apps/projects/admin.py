from django.contrib import admin

from apps.admin import ReadOnlyAdminMixin

from .models import Project


@admin.register(Project)
class ProjectAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("name", "workspace", "status", "creator", "updated_at")
    list_filter = ("status", "workspace")
    search_fields = ("name", "description", "workspace__name", "creator__email")
    readonly_fields = ("created_at", "updated_at")
