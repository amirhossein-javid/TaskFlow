from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models.functions import Lower, Trim
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from .managers import UserManager


class User(AbstractBaseUser, PermissionsMixin):
    email = models.EmailField(_("ایمیل"), unique=True)
    is_active = models.BooleanField(_("فعال"), default=True)
    is_staff = models.BooleanField(_("دسترسی مدیریت"), default=False)
    date_joined = models.DateTimeField(_("تاریخ عضویت"), default=timezone.now)

    objects = UserManager()

    USERNAME_FIELD = "email"
    REQUIRED_FIELDS = []

    class Meta:
        ordering = ["email"]
        constraints = [
            models.UniqueConstraint(
                Lower(Trim("email")),
                name="unique_user_email_ci",
                violation_error_message="کاربری با این ایمیل وجود دارد.",
            )
        ]
        verbose_name = _("کاربر")
        verbose_name_plural = _("کاربران")

    def __str__(self) -> str:
        return self.email

    def clean_fields(self, exclude=None):
        self.email = UserManager.normalize_email(self.email)
        super().clean_fields(exclude=exclude)

    def save(self, *args, **kwargs):
        if kwargs.get("update_fields") is None or "email" in kwargs["update_fields"]:
            self.email = UserManager.normalize_email(self.email)
        super().save(*args, **kwargs)


class Profile(models.Model):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="profile",
        verbose_name=_("کاربر"),
    )
    full_name = models.CharField(_("نام کامل"), max_length=255, default="")
    bio = models.TextField(_("درباره"), blank=True)
    avatar = models.ImageField(_("تصویر پروفایل"), upload_to="avatars/", blank=True)
    created_at = models.DateTimeField(_("تاریخ ایجاد"), auto_now_add=True)

    class Meta:
        verbose_name = _("پروفایل")
        verbose_name_plural = _("پروفایل‌ها")

    def __str__(self) -> str:
        return self.full_name or self.user.email
