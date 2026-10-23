import secrets
from datetime import timedelta

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.utils import timezone

from apps.accounts.models import User
from apps.projects.models import Project

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


def _locked_membership_state(workspace_id: int) -> dict[int, WorkspaceMembership]:
    """Lock a workspace and its memberships in a consistent order."""
    Workspace.objects.select_for_update().get(pk=workspace_id)
    memberships = (
        WorkspaceMembership.objects.select_for_update()
        .filter(workspace_id=workspace_id)
        .order_by("pk")
    )
    return {membership.pk: membership for membership in memberships}


def _current_membership(
    memberships: dict[int, WorkspaceMembership], membership_id: int
) -> WorkspaceMembership:
    try:
        return memberships[membership_id]
    except KeyError as error:
        raise ValidationError("این عضویت دیگر فعال نیست.") from error


def _owner_count(memberships: dict[int, WorkspaceMembership]) -> int:
    return sum(
        membership.role == WorkspaceMembership.Role.OWNER for membership in memberships.values()
    )


def _require_current_owner(*, memberships, actor):
    current = memberships.get(actor.pk)
    if current is None or current.role != WorkspaceMembership.Role.OWNER:
        raise PermissionDenied


@transaction.atomic
def update_workspace(*, workspace: Workspace, actor: WorkspaceMembership, name: str, slug: str):
    workspace = Workspace.objects.select_for_update().get(pk=workspace.pk)
    memberships = _locked_membership_state(workspace.pk)
    _require_current_owner(memberships=memberships, actor=actor)
    workspace.name = name
    workspace.slug = slug.strip().lower()
    workspace.full_clean()
    workspace.save(update_fields=["name", "slug", "updated_at"])
    return workspace


@transaction.atomic
def delete_workspace(*, workspace: Workspace, actor: WorkspaceMembership, confirmation: str):
    workspace = Workspace.objects.select_for_update().get(pk=workspace.pk)
    # Board/project services lock projects before memberships. Acquire these
    # gates before membership locks so cascading deletion cannot invert them.
    list(Project.objects.select_for_update().filter(workspace=workspace).order_by("pk"))
    memberships = _locked_membership_state(workspace.pk)
    _require_current_owner(memberships=memberships, actor=actor)
    if confirmation.strip() != workspace.name:
        raise ValidationError("نام واردشده با نام فضای کاری یکسان نیست.")
    workspace.delete()


@transaction.atomic
def change_membership_role(
    *, actor: WorkspaceMembership, target: WorkspaceMembership, role: str
) -> None:
    memberships = _locked_membership_state(actor.workspace_id)
    actor = _current_membership(memberships, actor.pk)
    target = _current_membership(memberships, target.pk)
    if actor.role != WorkspaceMembership.Role.OWNER:
        raise PermissionDenied
    if role not in WorkspaceMembership.Role.values:
        raise ValidationError("نقش انتخاب‌شده معتبر نیست.")
    if (
        target.role == WorkspaceMembership.Role.OWNER
        and role != WorkspaceMembership.Role.OWNER
        and _owner_count(memberships) == 1
    ):
        raise ValidationError("آخرین مالک فضای کاری را نمی‌توان تنزل نقش داد.")
    target.role = role
    target.save(update_fields=["role"])


@transaction.atomic
def remove_membership(*, actor: WorkspaceMembership, target: WorkspaceMembership) -> None:
    memberships = _locked_membership_state(actor.workspace_id)
    actor = _current_membership(memberships, actor.pk)
    target = _current_membership(memberships, target.pk)
    if actor.role not in [WorkspaceMembership.Role.OWNER, WorkspaceMembership.Role.ADMIN]:
        raise PermissionDenied
    if (
        actor.role == WorkspaceMembership.Role.ADMIN
        and target.role != WorkspaceMembership.Role.MEMBER
    ):
        raise PermissionDenied
    if actor.pk == target.pk:
        raise ValidationError("برای خروج از گزینهٔ ترک فضای کاری استفاده کنید.")
    if target.role == WorkspaceMembership.Role.OWNER and _owner_count(memberships) == 1:
        raise ValidationError("آخرین مالک فضای کاری را نمی‌توان حذف کرد.")
    target.delete()


@transaction.atomic
def leave_workspace(*, membership: WorkspaceMembership) -> None:
    memberships = _locked_membership_state(membership.workspace_id)
    membership = _current_membership(memberships, membership.pk)
    if membership.role == WorkspaceMembership.Role.OWNER and _owner_count(memberships) == 1:
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
    token_hash = WorkspaceInvitation.digest_token(token)
    workspace_id = (
        WorkspaceInvitation.objects.filter(token_hash=token_hash)
        .values_list("workspace_id", flat=True)
        .first()
    )
    if workspace_id is None:
        raise InvalidInvitation
    # Serialize account deletion before taking workspace locks: its SET_NULL
    # updates may need this workspace. NO KEY UPDATE still allows unrelated
    # writes to commit deferred User FK checks using KEY SHARE.
    user = User.objects.select_for_update(no_key=True).filter(pk=user.pk).first()
    if user is None:
        raise InvalidInvitation
    if not Workspace.objects.select_for_update().filter(pk=workspace_id).exists():
        raise InvalidInvitation
    invitation = (
        WorkspaceInvitation.objects.select_for_update(of=("self",))
        .select_related("workspace")
        .filter(token_hash=token_hash, workspace_id=workspace_id)
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
