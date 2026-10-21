import logging

from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.mail import send_mail
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views import View
from django.views.generic import FormView, ListView, TemplateView, UpdateView

from .forms import InvitationForm, MembershipRoleForm, WorkspaceDeleteForm, WorkspaceForm
from .mixins import (
    WorkspaceAccessMixin,
    WorkspaceManagerRequiredMixin,
    WorkspaceOwnerRequiredMixin,
)
from .models import WorkspaceInvitation, WorkspaceMembership
from .permissions import require_owner
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


class WorkspaceListView(LoginRequiredMixin, ListView):
    template_name = "workspaces/workspace_list.html"
    context_object_name = "memberships"
    http_method_names = ["get", "head", "options"]

    def get_queryset(self):
        return WorkspaceMembership.objects.filter(user=self.request.user).select_related(
            "workspace"
        )


class WorkspaceCreateView(LoginRequiredMixin, FormView):
    template_name = "workspaces/workspace_form.html"
    form_class = WorkspaceForm

    def form_valid(self, form):
        workspace = create_workspace(user=self.request.user, **form.cleaned_data)
        messages.success(self.request, "فضای کاری با موفقیت ساخته شد.")
        return redirect("workspaces:detail", slug=workspace.slug)


class WorkspaceDetailView(WorkspaceAccessMixin, TemplateView):
    template_name = "workspaces/workspace_detail.html"
    http_method_names = ["get", "head", "options"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["members"] = self.workspace.memberships.select_related("user", "user__profile")
        context["active_project_count"] = self.workspace.projects.filter(status="active").count()
        return context


class MemberListView(WorkspaceAccessMixin, TemplateView):
    template_name = "workspaces/member_list.html"
    http_method_names = ["get", "head", "options"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["members"] = self.workspace.memberships.select_related("user", "user__profile")
        context["pending_invitations"] = self.workspace.invitations.filter(
            accepted_at__isnull=True,
            revoked_at__isnull=True,
        )
        return context


class WorkspaceSettingsView(WorkspaceOwnerRequiredMixin, UpdateView):
    form_class = WorkspaceForm
    template_name = "workspaces/workspace_settings.html"

    def get_object(self, queryset=None):
        return self.workspace

    def form_valid(self, form):
        self.object = form.save()
        messages.success(self.request, "تنظیمات فضای کاری ذخیره شد.")
        return redirect("workspaces:settings", slug=self.object.slug)


class InviteMemberView(WorkspaceManagerRequiredMixin, FormView):
    form_class = InvitationForm
    template_name = "workspaces/invitation_form.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor_membership"] = self.membership
        return kwargs

    def form_valid(self, form):
        try:
            with transaction.atomic():
                invitation, token = create_invitation(
                    workspace=self.workspace,
                    actor=self.membership,
                    **form.cleaned_data,
                )
                accept_url = self.request.build_absolute_uri(
                    reverse("workspaces:invitation", kwargs={"token": token})
                )
                try:
                    delivered = send_mail(
                        subject=f"دعوت به فضای کاری {self.workspace.name}",
                        message=(
                            f"شما برای پیوستن به فضای کاری «{self.workspace.name}» دعوت "
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
            return self.form_invalid(form)
        except InvitationDeliveryError:
            logger.exception(
                "Workspace invitation email delivery failed",
                extra={"workspace_id": self.workspace.pk},
            )
            form.add_error(
                None,
                "ارسال دعوت‌نامه انجام نشد. لطفاً کمی بعد دوباره تلاش کنید.",
            )
            return self.form_invalid(form)
        messages.success(self.request, "دعوت‌نامه با موفقیت ارسال شد.")
        return redirect("workspaces:members", slug=self.workspace.slug)


class ChangeRoleView(WorkspaceOwnerRequiredMixin, View):
    http_method_names = ["post", "options"]

    def post(self, request, *args, **kwargs):
        target = get_object_or_404(
            WorkspaceMembership,
            pk=kwargs["membership_id"],
            workspace=self.workspace,
        )
        form = MembershipRoleForm(request.POST)
        if not form.is_valid():
            messages.error(request, "نقش انتخاب‌شده معتبر نیست.")
        else:
            try:
                change_membership_role(
                    actor=self.membership,
                    target=target,
                    role=form.cleaned_data["role"],
                )
            except ValidationError as error:
                messages.error(request, error.messages[0])
            else:
                messages.success(request, "نقش عضو به‌روزرسانی شد.")
        return redirect("workspaces:members", slug=self.workspace.slug)


class RemoveMemberView(WorkspaceManagerRequiredMixin, View):
    template_name = "workspaces/member_remove_confirm.html"
    http_method_names = ["get", "post", "head", "options"]

    def get_target(self):
        if not hasattr(self, "target"):
            self.target = get_object_or_404(
                WorkspaceMembership.objects.select_related("user", "user__profile"),
                pk=self.kwargs["membership_id"],
                workspace=self.workspace,
            )
            if (
                self.membership.role == WorkspaceMembership.Role.ADMIN
                and self.target.role != WorkspaceMembership.Role.MEMBER
            ):
                raise PermissionDenied("مدیران فقط می‌توانند اعضای عادی را حذف کنند.")
        return self.target

    def get(self, request, *args, **kwargs):
        return render(
            request,
            self.template_name,
            {
                "workspace": self.workspace,
                "membership": self.membership,
                "target": self.get_target(),
            },
        )

    def post(self, request, *args, **kwargs):
        try:
            remove_membership(actor=self.membership, target=self.get_target())
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            messages.success(request, "عضو از فضای کاری حذف شد.")
        return redirect("workspaces:members", slug=self.workspace.slug)


class WorkspaceLeaveView(WorkspaceAccessMixin, View):
    template_name = "workspaces/workspace_leave_confirm.html"
    http_method_names = ["get", "post", "head", "options"]

    def get(self, request, *args, **kwargs):
        return render(
            request,
            self.template_name,
            {"workspace": self.workspace, "membership": self.membership},
        )

    def post(self, request, *args, **kwargs):
        try:
            leave_workspace(membership=self.membership)
        except ValidationError as error:
            messages.error(request, error.messages[0])
            return redirect("workspaces:detail", slug=self.workspace.slug)
        messages.success(request, "از فضای کاری خارج شدید.")
        return redirect("workspaces:list")


class WorkspaceDeleteView(WorkspaceOwnerRequiredMixin, FormView):
    form_class = WorkspaceDeleteForm
    template_name = "workspaces/workspace_delete_confirm.html"

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["workspace"] = self.workspace
        return kwargs

    def form_valid(self, form):
        with transaction.atomic():
            locked_membership = WorkspaceMembership.objects.select_for_update().get(
                workspace=self.workspace,
                user=self.request.user,
            )
            require_owner(locked_membership)
            self.workspace.delete()
        messages.success(self.request, "فضای کاری برای همیشه حذف شد.")
        return redirect("workspaces:list")


class InvitationDetailView(View):
    template_name = "workspaces/invitation_detail.html"
    http_method_names = ["get", "post", "head", "options"]

    def get_invitation(self):
        invitation = (
            WorkspaceInvitation.objects.select_related("workspace")
            .filter(token_hash=WorkspaceInvitation.digest_token(self.kwargs["token"]))
            .first()
        )
        if not invitation:
            raise Http404
        return invitation

    def render_invitation(self, request):
        invitation = self.get_invitation()
        return render(
            request,
            self.template_name,
            {"invitation": invitation, "token": self.kwargs["token"]},
            status=200 if invitation.is_pending else 410,
        )

    def get(self, request, *args, **kwargs):
        return self.render_invitation(request)

    def post(self, request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        try:
            membership = accept_invitation(token=kwargs["token"], user=request.user)
        except PermissionDenied:
            messages.error(request, "این دعوت‌نامه برای ایمیل حساب فعلی شما صادر نشده است.")
        except InvalidInvitation:
            messages.error(request, "این دعوت‌نامه نامعتبر، منقضی یا قبلاً استفاده شده است.")
        else:
            messages.success(request, "با موفقیت به فضای کاری پیوستید.")
            return redirect("workspaces:detail", slug=membership.workspace.slug)
        return self.render_invitation(request)
