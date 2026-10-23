from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.decorators import method_decorator
from django.views import View
from django.views.generic import FormView, ListView, TemplateView, UpdateView

from .emails import INVITATION_DELIVERY_WARNING, send_invitation_email
from .forms import InvitationForm, MembershipRoleForm, WorkspaceDeleteForm, WorkspaceForm
from .mixins import (
    WorkspaceAccessMixin,
    WorkspaceManagerRequiredMixin,
    WorkspaceOwnerRequiredMixin,
)
from .models import Workspace, WorkspaceInvitation, WorkspaceMembership
from .services import (
    InvalidInvitation,
    accept_invitation,
    change_membership_role,
    create_invitation,
    create_workspace,
    delete_workspace,
    leave_workspace,
    remove_membership,
    resend_invitation,
    update_workspace,
)


class WorkspaceListView(LoginRequiredMixin, ListView):
    template_name = "workspaces/workspace_list.html"
    context_object_name = "memberships"
    http_method_names = ["get", "head"]

    def get_queryset(self):
        return WorkspaceMembership.objects.filter(user=self.request.user).select_related(
            "workspace"
        )


class WorkspaceCreateView(LoginRequiredMixin, FormView):
    template_name = "workspaces/workspace_form.html"
    form_class = WorkspaceForm
    http_method_names = ["get", "post"]

    def form_valid(self, form):
        workspace = create_workspace(user=self.request.user, **form.cleaned_data)
        messages.success(self.request, "فضای کاری با موفقیت ساخته شد.")
        return redirect("workspaces:detail", slug=workspace.slug)


class WorkspaceDetailView(WorkspaceAccessMixin, TemplateView):
    template_name = "workspaces/workspace_detail.html"
    http_method_names = ["get", "head"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["members"] = self.workspace.memberships.select_related("user", "user__profile")
        context["active_project_count"] = self.workspace.projects.filter(status="active").count()
        return context


class MemberListView(WorkspaceAccessMixin, TemplateView):
    template_name = "workspaces/member_list.html"
    http_method_names = ["get", "head"]

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
    http_method_names = ["get", "post"]

    def get_object(self, queryset=None):
        return self.workspace

    def form_valid(self, form):
        try:
            self.object = update_workspace(
                workspace=self.workspace, actor=self.membership, **form.cleaned_data
            )
        except Workspace.DoesNotExist as error:
            raise Http404 from error
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, "تنظیمات فضای کاری ذخیره شد.")
        return redirect("workspaces:settings", slug=self.object.slug)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class InviteMemberView(WorkspaceManagerRequiredMixin, FormView):
    form_class = InvitationForm
    template_name = "workspaces/invitation_form.html"
    http_method_names = ["get", "post"]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["actor_membership"] = self.membership
        return kwargs

    def form_valid(self, form):
        try:
            invitation, token = create_invitation(
                workspace=self.workspace,
                actor=self.membership,
                **form.cleaned_data,
            )
        except Workspace.DoesNotExist as error:
            raise Http404 from error
        except ValidationError as error:
            form.add_error("email", error)
            return self.form_invalid(form)
        if not send_invitation_email(
            invitation=invitation,
            workspace_name=self.workspace.name,
            accept_url=self.request.build_absolute_uri(
                reverse("workspaces:invitation", kwargs={"token": token})
            ),
        ):
            form.add_error(None, INVITATION_DELIVERY_WARNING)
            return self.form_invalid(form)
        messages.success(self.request, "دعوت‌نامه با موفقیت ارسال شد.")
        return redirect("workspaces:members", slug=self.workspace.slug)


@method_decorator(transaction.non_atomic_requests, name="dispatch")
class ResendInvitationView(WorkspaceManagerRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        try:
            invitation, token = resend_invitation(
                workspace=self.workspace,
                actor=self.membership,
                invitation_id=kwargs["invitation_id"],
            )
        except (Workspace.DoesNotExist, WorkspaceInvitation.DoesNotExist) as error:
            raise Http404 from error
        except ValidationError as error:
            messages.error(request, error.messages[0])
        else:
            if send_invitation_email(
                invitation=invitation,
                workspace_name=self.workspace.name,
                accept_url=request.build_absolute_uri(
                    reverse("workspaces:invitation", kwargs={"token": token})
                ),
            ):
                messages.success(
                    request, "دعوت‌نامه با پیوند جدید ارسال شد؛ پیوند قبلی دیگر معتبر نیست."
                )
            else:
                messages.error(
                    request, f"{INVITATION_DELIVERY_WARNING} پیوند قبلی دیگر معتبر نیست."
                )
        return redirect("workspaces:members", slug=self.workspace.slug)


class ChangeRoleView(WorkspaceOwnerRequiredMixin, View):
    http_method_names = ["post"]

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
    http_method_names = ["get", "post"]

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
    http_method_names = ["get", "post"]

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
    http_method_names = ["get", "post"]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["workspace"] = self.workspace
        return kwargs

    def form_valid(self, form):
        try:
            delete_workspace(
                workspace=self.workspace,
                actor=self.membership,
                confirmation=form.cleaned_data["confirmation"],
            )
        except Workspace.DoesNotExist as error:
            raise Http404 from error
        except ValidationError as error:
            form.add_error("confirmation", error)
            return self.form_invalid(form)
        messages.success(self.request, "فضای کاری برای همیشه حذف شد.")
        return redirect("workspaces:list")


class InvitationDetailView(View):
    template_name = "workspaces/invitation_detail.html"
    http_method_names = ["get", "post"]

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
        self.get_invitation()
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
