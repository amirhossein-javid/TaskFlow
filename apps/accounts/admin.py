from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin

from .forms import UserChangeForm, UserCreationForm
from .models import Profile, User


@admin.register(User)
class UserAdmin(BaseUserAdmin):
    form = UserChangeForm
    add_form = UserCreationForm

    list_display = ("email", "is_staff", "is_active", "date_joined")
    list_filter = ("is_staff", "is_active", "is_superuser")
    search_fields = ("email",)
    ordering = ("email",)
    filter_horizontal = ("groups", "user_permissions")
    readonly_fields = ("date_joined", "last_login")

    def get_deleted_objects(self, objs, request):
        deleted, counts, permissions, protected = super().get_deleted_objects(objs, request)
        # Profiles cannot be deleted independently, but must cascade with their users.
        permissions.discard(Profile._meta.verbose_name)
        return deleted, counts, permissions, protected

    fieldsets = (
        (None, {"fields": ("email", "password")}),
        (
            "مجوزها",
            {
                "fields": (
                    "is_active",
                    "is_staff",
                    "is_superuser",
                    "groups",
                    "user_permissions",
                )
            },
        ),
        ("تاریخ‌های مهم", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = (
        (
            None,
            {
                "classes": ("wide",),
                "fields": ("email", "password1", "password2", "is_staff", "is_active"),
            },
        ),
    )


@admin.register(Profile)
class ProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "full_name", "created_at")
    search_fields = ("user__email", "full_name")
    readonly_fields = ("created_at",)

    def has_delete_permission(self, request, obj=None):
        return False

    def get_readonly_fields(self, request, obj=None):
        fields = super().get_readonly_fields(request, obj)
        return (*fields, "user") if obj else fields
