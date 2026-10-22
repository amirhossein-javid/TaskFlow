from django.contrib import admin
from django.contrib.auth.admin import UserAdmin as BaseUserAdmin
from django.core.exceptions import PermissionDenied
from django.db import IntegrityError, transaction

from .db import is_email_conflict
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

    def changeform_view(self, request, object_id=None, form_url="", extra_context=None):
        try:
            return super().changeform_view(request, object_id, form_url, extra_context)
        except IntegrityError as error:
            if not is_email_conflict(error):
                raise
            # The Admin transaction has rolled back. Rebind against the winning
            # committed account so normal email validation renders a field error.
            return super().changeform_view(request, object_id, form_url, extra_context)

    def has_delete_permission(self, request, obj=None):
        return super().has_delete_permission(request, obj) and (
            obj is None or not obj.workspace_memberships.exists()
        )

    @transaction.atomic
    def delete_queryset(self, request, queryset):
        # Block new membership FK references until deletion commits. Existing
        # members must leave through the owner-safe workspace services first.
        user_ids = list(queryset.order_by("pk").values_list("pk", flat=True))
        locked_ids = []
        for user_id in user_ids:
            user = queryset.select_for_update(of=("self",)).filter(pk=user_id).first()
            if user is None:
                continue
            # Reject members before waiting on any later User: a workspace
            # writer may need KEY SHARE on this User to release its locks.
            if user.workspace_memberships.exists():
                raise PermissionDenied("برای حذف حساب، ابتدا عضویت‌های فضای کاری را پایان دهید.")
            locked_ids.append(user.pk)
        super().delete_queryset(request, queryset.filter(pk__in=locked_ids))

    def delete_model(self, request, obj):
        self.delete_queryset(request, User.objects.filter(pk=obj.pk))

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
