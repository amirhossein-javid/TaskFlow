from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import FormView, TemplateView

from apps.projects.models import Project
from apps.workspaces.permissions import require_manager

from .forms import ProjectLabelForm, TaskLabelForm
from .mixins import BoardAccessMixin
from .models import ProjectLabel
from .services import (
    create_project_label,
    delete_project_label,
    set_task_label,
    update_project_label,
)


class LabelListView(BoardAccessMixin, TemplateView):
    template_name = "boards/label_list.html"
    http_method_names = ["get", "head"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["labels"] = self.project.labels.all()
        context["is_manager"] = self.membership.role in {"owner", "admin"}
        return context


class LabelEditView(BoardAccessMixin, FormView):
    template_name = "boards/feature_form.html"
    form_class = ProjectLabelForm
    http_method_names = ["get", "post"]

    def check_workspace_permission(self):
        super().check_workspace_permission()
        self.label = None
        if "label_id" in self.kwargs:
            self.label = get_object_or_404(
                ProjectLabel, pk=self.kwargs["label_id"], project=self.project
            )
        require_manager(self.membership)

    def get(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            return self.back()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            messages.error(request, "پروژهٔ بایگانی‌شده فقط قابل مشاهده است.")
            return self.back()
        return super().post(request, *args, **kwargs)

    def back(self):
        return redirect("boards:label_list", slug=self.workspace.slug, project_id=self.project.pk)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.label or ProjectLabel(project=self.project)
        return kwargs

    def form_valid(self, form):
        try:
            if self.label:
                update_project_label(label=self.label, actor=self.membership, **form.cleaned_data)
            else:
                create_project_label(board=self.board, actor=self.membership, **form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        return self.back()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["heading"] = "ویرایش برچسب" if self.label else "ساخت برچسب"
        return context


class LabelDeleteView(BoardAccessMixin, View):
    http_method_names = ["get", "post"]

    def check_workspace_permission(self):
        super().check_workspace_permission()
        self.label = get_object_or_404(
            ProjectLabel, pk=self.kwargs["label_id"], project=self.project
        )
        require_manager(self.membership)

    def get(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            return redirect(
                "boards:label_list", slug=self.workspace.slug, project_id=self.project.pk
            )
        return render(
            request,
            "boards/feature_delete.html",
            {
                "workspace": self.workspace,
                "project": self.project,
                "heading": "حذف برچسب",
                "object_title": self.label.name,
            },
        )

    def post(self, request, *args, **kwargs):
        try:
            delete_project_label(label=self.label, actor=self.membership)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        return redirect("boards:label_list", slug=self.workspace.slug, project_id=self.project.pk)


class TaskLabelView(BoardAccessMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        task = self.get_task()
        form = TaskLabelForm(request.POST, project=self.project)
        if form.is_valid():
            try:
                set_task_label(task=task, actor=self.membership, **form.cleaned_data)
            except ValidationError as error:
                messages.error(request, error.messages[0])
        else:
            messages.error(request, "برچسب یا عملیات انتخاب‌شده معتبر نیست.")
        return redirect(
            "boards:task_detail",
            slug=self.workspace.slug,
            project_id=self.project.pk,
            task_id=task.pk,
        )
