from django.contrib import admin

from apps.admin import ReadOnlyAdminMixin

from .models import Workspace, WorkspaceInvitation, WorkspaceMembership


class WorkspaceMembershipInline(ReadOnlyAdminMixin, admin.TabularInline):
    model = WorkspaceMembership
    extra = 0


@admin.register(Workspace)
class WorkspaceAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("name", "slug", "created_by", "created_at")
    search_fields = ("name", "slug", "created_by__email")
    inlines = (WorkspaceMembershipInline,)


@admin.register(WorkspaceInvitation)
class WorkspaceInvitationAdmin(ReadOnlyAdminMixin, admin.ModelAdmin):
    list_display = ("email", "workspace", "role", "expires_at", "accepted_at", "revoked_at")
    list_filter = ("role", "accepted_at", "revoked_at")
    search_fields = ("email", "workspace__name")
    readonly_fields = ("token_hash", "created_at", "accepted_at", "revoked_at")
