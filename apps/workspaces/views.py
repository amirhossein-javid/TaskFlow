import logging

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_http_methods, require_POST

from .forms import (
    InvitationForm,
    MembershipRoleForm,
    WorkspaceDeleteForm,
    WorkspaceForm,
)
from .models import WorkspaceInvitation, WorkspaceMembership
from .permissions import get_workspace_membership, require_manager, require_owner
from .services import (
    InvalidInvitation,
    accept_invitation,
    change_membership_role,
    create_invitation,
    create_workspace,
    leave_workspace,
    remove_membership,
)

logger = logging.getLogger(__name__)


class InvitationDeliveryError(Exception):
    """Raised when an invitation email backend does not confirm delivery."""


@login_required
def workspace_list(request):
    memberships = WorkspaceMembership.objects.filter(user=request.user).select_related("workspace")
    return render(request, "workspaces/workspace_list.html", {"memberships": memberships})


@login_required
@require_http_methods(["GET", "POST"])
def workspace_create(request):
    form = WorkspaceForm(request.POST or None)
    if request.method == "POST" and form.is_valid():
        workspace = create_workspace(user=request.user, **form.cleaned_data)
        messages.success(request, "فضای کاری با موفقیت ساخته شد.")
        return redirect("workspaces:detail", slug=workspace.slug)
    return render(request, "workspaces/workspace_form.html", {"form": form})


@login_required
def workspace_detail(request, slug):
    workspace, membership = get_workspace_membership(user=request.user, slug=slug)
    members = workspace.memberships.select_related("user", "user__profile")
    active_project_count = workspace.projects.filter(status="active").count()
    return render(
        request,
        "workspaces/workspace_detail.html",
        {
            "workspace": workspace,
            "membership": membership,
            "members": members,
            "active_project_count": active_project_count,
        },
    )


@login_required
def member_list(request, slug):
    workspace, membership = get_workspace_membership(user=request.user, slug=slug)
    members = workspace.memberships.select_related("user", "user__profile")
    pending_invitations = workspace.invitations.filter(
        accepted_at__isnull=True, revoked_at__isnull=True
    )
    return render(
        request,
        "workspaces/member_list.html",
        {
            "workspace": workspace,
            "membership": membership,
            "members": members,
            "pending_invitations": pending_invitations,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def workspace_settings(request, slug):
    workspace, membership = get_workspace_membership(user=request.user, slug=slug)
    require_owner(membership)
    form = WorkspaceForm(request.POST or None, instance=workspace)
    if request.method == "POST" and form.is_valid():
        workspace = form.save()
        messages.success(request, "تنظیمات فضای کاری ذخیره شد.")
        return redirect("workspaces:settings", slug=workspace.slug)
    return render(
        request,
        "workspaces/workspace_settings.html",
        {"workspace": workspace, "membership": membership, "form": form},
    )


@login_required
@require_http_methods(["GET", "POST"])
def invite_member(request, slug):
    workspace, membership = get_workspace_membership(user=request.user, slug=slug)
    require_manager(membership)
    form = InvitationForm(request.POST or None, actor_membership=membership)
    if request.method == "POST" and form.is_valid():
        try:
            with transaction.atomic():
                invitation, token = create_invitation(
                    workspace=workspace,
                    actor=membership,
                    **form.cleaned_data,
                )
                accept_url = request.build_absolute_uri(
                    reverse("workspaces:invitation", kwargs={"token": token})
                )
                try:
                    delivered = send_mail(
                        subject=f"دعوت به فضای کاری {workspace.name}",
                        message=(
                            f"شما برای پیوستن به فضای کاری «{workspace.name}» دعوت "
                            "شده‌اید.\n\n"
                            "برای مشاهده و پذیرش دعوت از این پیوند استفاده کنید:\n"
                            f"{accept_url}\n\n"
                            "این پیوند محدود، یک‌بارمصرف و مخصوص همین ایمیل است."
                        ),
                        from_email=None,
                        recipient_list=[invitation.email],
                        fail_silently=False,
                    )
                except Exception as error:
                    raise InvitationDeliveryError from error
                if delivered != 1:
                    raise InvitationDeliveryError
        except ValidationError as error:
            form.add_error("email", error)
        except InvitationDeliveryError:
            logger.exception(
                "Workspace invitation email delivery failed",
                extra={"workspace_id": workspace.pk},
            )
            form.add_error(
                None,
                "ارسال دعوت‌نامه انجام نشد. لطفاً کمی بعد دوباره تلاش کنید.",
            )
        else:
            messages.success(request, "دعوت‌نامه با موفقیت ارسال شد.")
            return redirect("workspaces:members", slug=workspace.slug)
    return render(
        request,
        "workspaces/invitation_form.html",
        {"workspace": workspace, "membership": membership, "form": form},
    )


@login_required
@require_POST
def change_role(request, slug, membership_id):
    workspace, actor = get_workspace_membership(user=request.user, slug=slug)
    require_owner(actor)
    target = get_object_or_404(WorkspaceMembership, pk=membership_id, workspace=workspace)
    form = MembershipRoleForm(request.POST)
    if not form.is_valid():
        messages.error(request, "نقش انتخاب‌شده معتبر نیست.")
    else:
        try:
            change_membership_role(actor=actor, target=target, role=form.cleaned_data["role"])
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, "نقش عضو به‌روزرسانی شد.")
    return redirect("workspaces:members", slug=workspace.slug)


@login_required
@require_http_methods(["GET", "POST"])
def remove_member(request, slug, membership_id):
    workspace, actor = get_workspace_membership(user=request.user, slug=slug)
    require_manager(actor)
    target = get_object_or_404(
        WorkspaceMembership.objects.select_related("user", "user__profile"),
        pk=membership_id,
        workspace=workspace,
    )
    if (
        actor.role == WorkspaceMembership.Role.ADMIN
        and target.role != WorkspaceMembership.Role.MEMBER
    ):
        raise PermissionDenied("مدیران فقط می‌توانند اعضای عادی را حذف کنند.")
    if request.method == "POST":
        try:
            remove_membership(actor=actor, target=target)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, "عضو از فضای کاری حذف شد.")
        return redirect("workspaces:members", slug=workspace.slug)
    return render(
        request,
        "workspaces/member_remove_confirm.html",
        {"workspace": workspace, "membership": actor, "target": target},
    )


@login_required
@require_http_methods(["GET", "POST"])
def workspace_leave(request, slug):
    workspace, membership = get_workspace_membership(user=request.user, slug=slug)
    if request.method == "POST":
        try:
            leave_workspace(membership=membership)
        except ValidationError as error:
            messages.error(request, error.messages[0])
            return redirect("workspaces:detail", slug=workspace.slug)
        messages.success(request, "از فضای کاری خارج شدید.")
        return redirect("workspaces:list")
    return render(
        request,
        "workspaces/workspace_leave_confirm.html",
        {"workspace": workspace, "membership": membership},
    )


@login_required
@require_http_methods(["GET", "POST"])
def workspace_delete(request, slug):
    workspace, membership = get_workspace_membership(user=request.user, slug=slug)
    require_owner(membership)
    form = WorkspaceDeleteForm(request.POST or None, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        with transaction.atomic():
            locked_membership = WorkspaceMembership.objects.select_for_update().get(
                workspace=workspace, user=request.user
            )
            require_owner(locked_membership)
            workspace.delete()
        messages.success(request, "فضای کاری برای همیشه حذف شد.")
        return redirect("workspaces:list")
    return render(
        request,
        "workspaces/workspace_delete_confirm.html",
        {"workspace": workspace, "membership": membership, "form": form},
    )


@require_http_methods(["GET", "POST"])
def invitation_detail(request, token):
    invitation = (
        WorkspaceInvitation.objects.select_related("workspace")
        .filter(token_hash=WorkspaceInvitation.digest_token(token))
        .first()
    )
    if not invitation:
        raise Http404
    if request.method == "POST":
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        try:
            membership = accept_invitation(token=token, user=request.user)
        except PermissionDenied:
            messages.error(request, "این دعوت‌نامه برای ایمیل حساب فعلی شما صادر نشده است.")
        except InvalidInvitation:
            messages.error(request, "این دعوت‌نامه نامعتبر، منقضی یا قبلاً استفاده شده است.")
        else:
            messages.success(request, "با موفقیت به فضای کاری پیوستید.")
            return redirect("workspaces:detail", slug=membership.workspace.slug)
    return render(
        request,
        "workspaces/invitation_detail.html",
        {"invitation": invitation, "token": token},
        status=200 if invitation.is_pending else 410,
    )
