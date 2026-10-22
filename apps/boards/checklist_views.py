from django.contrib import messages
from django.core.exceptions import ValidationError
from django.shortcuts import get_object_or_404, redirect, render
from django.views import View
from django.views.generic import FormView

from apps.projects.models import Project

from .forms import ChecklistItemForm, ChecklistItemStateForm, TaskChecklistForm
from .mixins import BoardAccessMixin
from .models import ChecklistItem, TaskChecklist
from .services import (
    create_checklist,
    create_checklist_item,
    delete_checklist,
    delete_checklist_item,
    set_checklist_item_completed,
    update_checklist,
    update_checklist_item,
)


class ChecklistAccessMixin(BoardAccessMixin):
    def check_workspace_permission(self):
        super().check_workspace_permission()
        self.task = self.get_task()
        self.checklist = None
        self.item = None
        if "checklist_id" in self.kwargs:
            self.checklist = get_object_or_404(
                TaskChecklist.objects.select_related("task__column"),
                pk=self.kwargs["checklist_id"],
                task=self.task,
            )
        if "item_id" in self.kwargs:
            self.item = get_object_or_404(
                ChecklistItem.objects.select_related("checklist__task__column"),
                pk=self.kwargs["item_id"],
                checklist=self.checklist,
            )

    def back(self):
        return redirect(
            "boards:task_detail",
            slug=self.workspace.slug,
            project_id=self.project.pk,
            task_id=self.task.pk,
        )

    def get(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            return self.back()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            messages.error(request, "پروژهٔ بایگانی‌شده فقط قابل مشاهده است.")
            return self.back()
        return super().post(request, *args, **kwargs)


class ChecklistEditView(ChecklistAccessMixin, FormView):
    template_name = "boards/feature_form.html"
    form_class = TaskChecklistForm
    http_method_names = ["get", "post"]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.checklist or TaskChecklist(task=self.task)
        return kwargs

    def form_valid(self, form):
        try:
            if self.checklist:
                update_checklist(
                    checklist=self.checklist, actor=self.membership, **form.cleaned_data
                )
            else:
                create_checklist(task=self.task, actor=self.membership, **form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        return self.back()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["heading"] = "ویرایش چک‌لیست" if self.checklist else "ساخت چک‌لیست"
        return context


class ChecklistItemEditView(ChecklistAccessMixin, FormView):
    template_name = "boards/feature_form.html"
    form_class = ChecklistItemForm
    http_method_names = ["get", "post"]

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = self.item or ChecklistItem(checklist=self.checklist)
        return kwargs

    def form_valid(self, form):
        try:
            if self.item:
                update_checklist_item(item=self.item, actor=self.membership, **form.cleaned_data)
            else:
                create_checklist_item(
                    checklist=self.checklist, actor=self.membership, **form.cleaned_data
                )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        return self.back()

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["heading"] = "ویرایش مورد چک‌لیست" if self.item else "افزودن مورد چک‌لیست"
        return context


class ChecklistDeleteView(ChecklistAccessMixin, View):
    http_method_names = ["get", "post"]

    def get(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            return self.back()
        return render(
            request,
            "boards/feature_delete.html",
            {
                "workspace": self.workspace,
                "project": self.project,
                "heading": "حذف مورد چک‌لیست" if self.item else "حذف چک‌لیست و موارد آن",
                "object_title": self.item.text if self.item else self.checklist.title,
            },
        )

    def post(self, request, *args, **kwargs):
        try:
            if self.item:
                delete_checklist_item(item=self.item, actor=self.membership)
            else:
                delete_checklist(checklist=self.checklist, actor=self.membership)
        except ValidationError as error:
            messages.error(request, error.messages[0])
        return self.back()


class ChecklistItemStateView(ChecklistAccessMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        form = ChecklistItemStateForm(request.POST)
        if form.is_valid():
            try:
                set_checklist_item_completed(
                    item=self.item, actor=self.membership, **form.cleaned_data
                )
            except ValidationError as error:
                messages.error(request, error.messages[0])
        else:
            messages.error(request, "وضعیت مورد معتبر نیست.")
        return self.back()
