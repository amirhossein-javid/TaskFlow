import json

from django.contrib import messages
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import DetailView, FormView, TemplateView, UpdateView

from apps.projects.models import Project
from apps.workspaces.models import WorkspaceMembership

from .forms import BoardColumnForm, TaskForm
from .mixins import BoardAccessMixin, BoardManagerRequiredMixin
from .models import Task
from .services import (
    create_column,
    create_task,
    delete_column,
    delete_task,
    move_task,
    nudge_task,
    rename_column,
    reorder_columns,
    shift_column,
    update_task,
)


def _service_error(request, error: ValidationError) -> None:
    messages.error(request, error.messages[0])


class BoardDetailView(BoardAccessMixin, TemplateView):
    template_name = "boards/board_detail.html"
    http_method_names = ["get", "head"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["columns"] = self.board.columns.prefetch_related(
            "tasks__assignee",
            "tasks__assignee__profile",
        )
        context["column_form"] = BoardColumnForm()
        context["is_manager"] = self.membership.role in {
            WorkspaceMembership.Role.OWNER,
            WorkspaceMembership.Role.ADMIN,
        }
        return context


class ColumnCreateView(BoardManagerRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        form = BoardColumnForm(request.POST)
        if form.is_valid():
            try:
                create_column(board=self.board, actor=self.membership, **form.cleaned_data)
            except ValidationError as error:
                _service_error(request, error)
            else:
                messages.success(request, "ستون جدید ساخته شد.")
        else:
            messages.error(request, form.errors.get("name", ["نام ستون معتبر نیست."])[0])
        return redirect("boards:detail", slug=self.workspace.slug, project_id=self.project.pk)


class ColumnRenameView(BoardManagerRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        column = self.get_column()
        form = BoardColumnForm(request.POST, instance=column)
        if form.is_valid():
            try:
                rename_column(column=column, actor=self.membership, **form.cleaned_data)
            except ValidationError as error:
                _service_error(request, error)
            else:
                messages.success(request, "نام ستون تغییر کرد.")
        else:
            messages.error(request, form.errors.get("name", ["نام ستون معتبر نیست."])[0])
        return redirect("boards:detail", slug=self.workspace.slug, project_id=self.project.pk)


class ColumnReorderView(BoardManagerRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        try:
            payload = json.loads(request.body)
            ordered_ids = [int(column_id) for column_id in payload["columns"]]
            reorder_columns(
                board=self.board,
                actor=self.membership,
                ordered_ids=ordered_ids,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "درخواست نامعتبر است."}, status=400)
        except ValidationError as error:
            return JsonResponse({"error": error.messages[0]}, status=400)
        return JsonResponse({"ok": True})


class ColumnShiftView(BoardManagerRequiredMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        try:
            shift_column(
                column=self.get_column(),
                actor=self.membership,
                direction=request.POST.get("direction", ""),
            )
        except ValidationError as error:
            _service_error(request, error)
        return redirect("boards:detail", slug=self.workspace.slug, project_id=self.project.pk)


class ColumnDeleteView(BoardManagerRequiredMixin, View):
    template_name = "boards/column_delete_confirm.html"
    http_method_names = ["get", "post"]

    def get(self, request, *args, **kwargs):
        return render(
            request,
            self.template_name,
            {
                "workspace": self.workspace,
                "membership": self.membership,
                "project": self.project,
                "column": self.get_column(),
            },
        )

    def post(self, request, *args, **kwargs):
        try:
            delete_column(column=self.get_column(), actor=self.membership)
        except ValidationError as error:
            _service_error(request, error)
        else:
            messages.success(request, "ستون حذف شد.")
        return redirect("boards:detail", slug=self.workspace.slug, project_id=self.project.pk)


class TaskCreateView(BoardAccessMixin, FormView):
    template_name = "boards/task_form.html"
    form_class = TaskForm
    http_method_names = ["get", "post"]

    def check_workspace_permission(self):
        super().check_workspace_permission()
        self.column = self.get_column()

    def archived_response(self):
        messages.error(self.request, "پروژهٔ بایگانی‌شده فقط قابل مشاهده است.")
        return redirect("boards:detail", slug=self.workspace.slug, project_id=self.project.pk)

    def get(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            return self.archived_response()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            return self.archived_response()
        return super().post(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["instance"] = Task(column=self.column)
        kwargs["workspace"] = self.workspace
        return kwargs

    def form_valid(self, form):
        try:
            task = create_task(
                column=self.column,
                actor=self.membership,
                **form.cleaned_data,
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, "وظیفه ساخته شد.")
        return redirect(
            "boards:task_detail",
            slug=self.workspace.slug,
            project_id=self.project.pk,
            task_id=task.pk,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["column"] = self.column
        context["task"] = None
        return context


class TaskDetailView(BoardAccessMixin, DetailView):
    template_name = "boards/task_detail.html"
    context_object_name = "task"
    http_method_names = ["get", "head"]

    def get_object(self, queryset=None):
        return self.get_task()


class TaskEditView(BoardAccessMixin, UpdateView):
    template_name = "boards/task_form.html"
    form_class = TaskForm
    context_object_name = "task"
    http_method_names = ["get", "post"]

    def get_object(self, queryset=None):
        return self.get_task()

    def archived_response(self):
        messages.error(self.request, "پروژهٔ بایگانی‌شده فقط قابل مشاهده است.")
        return redirect(
            "boards:task_detail",
            slug=self.workspace.slug,
            project_id=self.project.pk,
            task_id=self.get_task().pk,
        )

    def get(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            return self.archived_response()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            return self.archived_response()
        return super().post(request, *args, **kwargs)

    def get_form_kwargs(self):
        kwargs = super().get_form_kwargs()
        kwargs["workspace"] = self.workspace
        return kwargs

    def form_valid(self, form):
        try:
            self.object = update_task(
                task=self.get_task(),
                actor=self.membership,
                **form.cleaned_data,
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, "وظیفه به‌روزرسانی شد.")
        return redirect(
            "boards:task_detail",
            slug=self.workspace.slug,
            project_id=self.project.pk,
            task_id=self.object.pk,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context["column"] = self.get_task().column
        return context


class TaskDeleteView(BoardAccessMixin, View):
    template_name = "boards/task_delete_confirm.html"
    http_method_names = ["get", "post"]

    def archived_response(self):
        task = self.get_task()
        messages.error(self.request, "پروژهٔ بایگانی‌شده فقط قابل مشاهده است.")
        return redirect(
            "boards:task_detail",
            slug=self.workspace.slug,
            project_id=self.project.pk,
            task_id=task.pk,
        )

    def get(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            return self.archived_response()
        return render(
            request,
            self.template_name,
            {
                "workspace": self.workspace,
                "membership": self.membership,
                "project": self.project,
                "task": self.get_task(),
            },
        )

    def post(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            return self.archived_response()
        try:
            delete_task(task=self.get_task(), actor=self.membership)
        except ValidationError as error:
            _service_error(request, error)
        else:
            messages.success(request, "وظیفه حذف شد.")
        return redirect("boards:detail", slug=self.workspace.slug, project_id=self.project.pk)


class TaskMoveView(BoardAccessMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        task = self.get_task()
        try:
            payload = json.loads(request.body)
            target_column = self.get_column(int(payload["column"]))
            target_position = int(payload["position"])
            task = move_task(
                task=task,
                actor=self.membership,
                target_column=target_column,
                target_position=target_position,
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError):
            return JsonResponse({"error": "درخواست جابه‌جایی معتبر نیست."}, status=400)
        except ValidationError as error:
            return JsonResponse({"error": error.messages[0]}, status=400)
        return JsonResponse({"ok": True, "column": task.column_id, "position": task.position})


class TaskNudgeView(BoardAccessMixin, View):
    http_method_names = ["post"]

    def post(self, request, *args, **kwargs):
        try:
            nudge_task(
                task=self.get_task(),
                actor=self.membership,
                direction=request.POST.get("direction", ""),
            )
        except ValidationError as error:
            _service_error(request, error)
        return redirect("boards:detail", slug=self.workspace.slug, project_id=self.project.pk)
