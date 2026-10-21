import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User

from .models import Workspace, WorkspaceInvitation, WorkspaceMembership


class InvalidInvitation(Exception):
    """Raised when an invitation cannot be accepted."""


@transaction.atomic
def create_workspace(*, user: User, name: str, slug: str) -> Workspace:
    workspace = Workspace.objects.create(name=name, slug=slug, created_by=user)
    WorkspaceMembership.objects.create(
        workspace=workspace,
        user=user,
        role=WorkspaceMembership.Role.OWNER,
    )
    return workspace


def _locked_memberships(workspace: Workspace):
    Workspace.objects.select_for_update().get(pk=workspace.pk)
    return WorkspaceMembership.objects.select_for_update().filter(workspace=workspace)


@transaction.atomic
def change_membership_role(
    *, actor: WorkspaceMembership, target: WorkspaceMembership, role: str
) -> None:
    memberships = _locked_memberships(actor.workspace)
    actor = memberships.get(pk=actor.pk)
    target = memberships.get(pk=target.pk)
    if actor.role != WorkspaceMembership.Role.OWNER:
        raise PermissionDenied
    if role not in WorkspaceMembership.Role.values:
        raise ValidationError("نقش انتخاب‌شده معتبر نیست.")
    if (
        target.role == WorkspaceMembership.Role.OWNER
        and role != WorkspaceMembership.Role.OWNER
        and memberships.filter(role=WorkspaceMembership.Role.OWNER).count() == 1
    ):
        raise ValidationError("آخرین مالک فضای کاری را نمی‌توان تنزل نقش داد.")
    target.role = role
    target.save(update_fields=["role"])


@transaction.atomic
def remove_membership(*, actor: WorkspaceMembership, target: WorkspaceMembership) -> None:
    memberships = _locked_memberships(actor.workspace)
    actor = memberships.get(pk=actor.pk)
    target = memberships.get(pk=target.pk)
    if actor.role not in [WorkspaceMembership.Role.OWNER, WorkspaceMembership.Role.ADMIN]:
        raise PermissionDenied
    if (
        actor.role == WorkspaceMembership.Role.ADMIN
        and target.role != WorkspaceMembership.Role.MEMBER
    ):
        raise PermissionDenied
    if actor.pk == target.pk:
        raise ValidationError("برای خروج از گزینهٔ ترک فضای کاری استفاده کنید.")
    if (
        target.role == WorkspaceMembership.Role.OWNER
        and memberships.filter(role=WorkspaceMembership.Role.OWNER).count() == 1
    ):
        raise ValidationError("آخرین مالک فضای کاری را نمی‌توان حذف کرد.")
    target.delete()


@transaction.atomic
def leave_workspace(*, membership: WorkspaceMembership) -> None:
    memberships = _locked_memberships(membership.workspace)
    membership = memberships.get(pk=membership.pk)
    if (
        membership.role == WorkspaceMembership.Role.OWNER
        and memberships.filter(role=WorkspaceMembership.Role.OWNER).count() == 1
    ):
        raise ValidationError("آخرین مالک نمی‌تواند فضای کاری را ترک کند.")
    membership.delete()


@transaction.atomic
def create_invitation(
    *, workspace: Workspace, actor: WorkspaceMembership, email: str, role: str
) -> tuple[WorkspaceInvitation, str]:
    Workspace.objects.select_for_update().get(pk=workspace.pk)
    actor = WorkspaceMembership.objects.select_for_update().get(pk=actor.pk, workspace=workspace)
    if actor.role not in [WorkspaceMembership.Role.OWNER, WorkspaceMembership.Role.ADMIN]:
        raise PermissionDenied
    allowed_roles = [WorkspaceMembership.Role.MEMBER]
    if actor.role == WorkspaceMembership.Role.OWNER:
        allowed_roles.append(WorkspaceMembership.Role.ADMIN)
    if role not in allowed_roles:
        raise PermissionDenied
    normalized_email = User.objects.normalize_email(email).lower()
    if WorkspaceMembership.objects.filter(
        workspace=workspace, user__email__iexact=normalized_email
    ).exists():
        raise ValidationError("این کاربر از قبل عضو فضای کاری است.")

    pending = WorkspaceInvitation.objects.select_for_update().filter(
        workspace=workspace,
        email__iexact=normalized_email,
        accepted_at__isnull=True,
        revoked_at__isnull=True,
    )
    now = timezone.now()
    pending.filter(expires_at__lte=now).update(revoked_at=now)
    if pending.filter(expires_at__gt=now).exists():
        raise ValidationError("برای این ایمیل یک دعوت فعال وجود دارد.")

    token = secrets.token_urlsafe(32)
    invitation = WorkspaceInvitation.objects.create(
        workspace=workspace,
        email=normalized_email,
        role=role,
        token_hash=WorkspaceInvitation.digest_token(token),
        invited_by=actor.user,
        expires_at=now + timedelta(days=settings.WORKSPACE_INVITATION_EXPIRY_DAYS),
    )
    return invitation, token


@transaction.atomic
def accept_invitation(*, token: str, user: User) -> WorkspaceMembership:
    invitation = (
        WorkspaceInvitation.objects.select_for_update()
        .select_related("workspace")
        .filter(token_hash=WorkspaceInvitation.digest_token(token))
        .first()
    )
    if not invitation or not invitation.is_pending:
        raise InvalidInvitation
    if invitation.email.casefold() != user.email.casefold():
        raise PermissionDenied
    if WorkspaceMembership.objects.filter(workspace=invitation.workspace, user=user).exists():
        raise InvalidInvitation
    membership = WorkspaceMembership.objects.create(
        workspace=invitation.workspace,
        user=user,
        role=invitation.role,
    )
    invitation.accepted_at = timezone.now()
    invitation.accepted_by = user
    invitation.save(update_fields=["accepted_at", "accepted_by"])
    return membership
