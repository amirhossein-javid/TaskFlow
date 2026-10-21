import hashlib

from django.conf import settings
from django.db import models
from django.db.models.functions import Lower
from django.utils import timezone
from django.utils.translation import gettext_lazy as _


class Workspace(models.Model):
    name = models.CharField(_("نام"), max_length=120)
    slug = models.SlugField(_("شناسه"), max_length=80, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="created_workspaces",
        verbose_name=_("سازنده"),
    )
    members = models.ManyToManyField(
        settings.AUTH_USER_MODEL,
        through="WorkspaceMembership",
        related_name="workspaces",
        verbose_name=_("اعضا"),
    )
    created_at = models.DateTimeField(_("تاریخ ایجاد"), auto_now_add=True)
    updated_at = models.DateTimeField(_("تاریخ به‌روزرسانی"), auto_now=True)

    class Meta:
        ordering = ["name", "id"]
        constraints = [models.UniqueConstraint(Lower("slug"), name="unique_workspace_slug_ci")]
        verbose_name = _("فضای کاری")
        verbose_name_plural = _("فضاهای کاری")

    def __str__(self) -> str:
        return self.name

    def save(self, *args, **kwargs):
        self.slug = self.slug.strip().lower()
        super().save(*args, **kwargs)


class WorkspaceMembership(models.Model):
    class Role(models.TextChoices):
        OWNER = "owner", _("مالک")
        ADMIN = "admin", _("مدیر")
        MEMBER = "member", _("عضو")

    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="memberships",
        verbose_name=_("فضای کاری"),
    )
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.CASCADE,
        related_name="workspace_memberships",
        verbose_name=_("کاربر"),
    )
    role = models.CharField(_("نقش"), max_length=10, choices=Role.choices)
    joined_at = models.DateTimeField(_("تاریخ عضویت"), auto_now_add=True)

    class Meta:
        ordering = ["joined_at", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["workspace", "user"], name="unique_workspace_membership"
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=["owner", "admin", "member"]),
                name="valid_workspace_membership_role",
            ),
        ]
        verbose_name = _("عضویت فضای کاری")
        verbose_name_plural = _("عضویت‌های فضای کاری")

    def __str__(self) -> str:
        return f"{self.user} · {self.workspace}"


class WorkspaceInvitation(models.Model):
    workspace = models.ForeignKey(
        Workspace,
        on_delete=models.CASCADE,
        related_name="invitations",
        verbose_name=_("فضای کاری"),
    )
    email = models.EmailField(_("ایمیل"))
    role = models.CharField(
        _("نقش"),
        max_length=10,
        choices=[
            (WorkspaceMembership.Role.ADMIN, _("مدیر")),
            (WorkspaceMembership.Role.MEMBER, _("عضو")),
        ],
        default=WorkspaceMembership.Role.MEMBER,
    )
    token_hash = models.CharField(max_length=64, unique=True, editable=False)
    invited_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        related_name="workspace_invitations_sent",
        verbose_name=_("دعوت‌کننده"),
    )
    accepted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="workspace_invitations_accepted",
        verbose_name=_("پذیرنده"),
    )
    expires_at = models.DateTimeField(_("تاریخ انقضا"))
    accepted_at = models.DateTimeField(_("تاریخ پذیرش"), null=True, blank=True)
    revoked_at = models.DateTimeField(_("تاریخ لغو"), null=True, blank=True)
    created_at = models.DateTimeField(_("تاریخ ایجاد"), auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]
        constraints = [
            models.UniqueConstraint(
                Lower("email"),
                "workspace",
                condition=models.Q(accepted_at__isnull=True, revoked_at__isnull=True),
                name="unique_active_workspace_invitation_ci",
            ),
            models.CheckConstraint(
                condition=models.Q(role__in=["admin", "member"]),
                name="valid_workspace_invitation_role",
            ),
        ]
        verbose_name = _("دعوت فضای کاری")
        verbose_name_plural = _("دعوت‌های فضای کاری")

    def __str__(self) -> str:
        return f"{self.email} · {self.workspace}"

    @property
    def is_expired(self) -> bool:
        return self.expires_at <= timezone.now()

    @property
    def is_pending(self) -> bool:
        return not self.accepted_at and not self.revoked_at and not self.is_expired

    @staticmethod
    def digest_token(token: str) -> str:
        return hashlib.sha256(token.encode()).hexdigest()
