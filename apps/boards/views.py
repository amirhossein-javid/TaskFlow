import json

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import BigIntegerField, Case, Exists, F, OuterRef, Prefetch, Q, When
from django.db.models.fields.json import KeyTextTransform
from django.db.models.functions import Cast
from django.http import JsonResponse
from django.shortcuts import redirect, render
from django.views import View
from django.views.generic import DetailView, FormView, TemplateView, UpdateView

from apps.projects.models import Project
from apps.workspaces.models import WorkspaceMembership

from .forms import BoardColumnForm, TaskCommentForm, TaskFilterForm, TaskForm
from .mixins import BoardAccessMixin, BoardManagerRequiredMixin
from .models import Task, TaskActivity
from .services import (
    create_column,
    create_task,
    create_task_comment,
    delete_column,
    delete_task,
    delete_task_comment,
    move_task,
    nudge_task,
    rename_column,
    reorder_columns,
    shift_column,
    update_task,
    update_task_comment,
)


def _service_error(request, error: ValidationError) -> None:
    messages.error(request, error.messages[0])


class BoardDetailView(BoardAccessMixin, TemplateView):
    template_name = "boards/board_detail.html"
    http_method_names = ["get", "head"]

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        form = TaskFilterForm(self.request.GET, board=self.board, workspace=self.workspace)
        valid = form.is_valid()
        context["filter_form"] = form
        context["has_active_filters"] = not valid or any(form.cleaned_data.values())
        context["can_move"] = (
            self.project.status == Project.Status.ACTIVE and not context["has_active_filters"]
        )
        context["columns"] = self.board.columns.prefetch_related(
            Prefetch("tasks", queryset=self.get_task_queryset(form)),
        )
        context["column_form"] = BoardColumnForm()
        context["is_manager"] = self.membership.role in {
            WorkspaceMembership.Role.OWNER,
            WorkspaceMembership.Role.ADMIN,
        }
        return context

    def get_task_queryset(self, form):
        tasks = Task.objects.filter(column__board=self.board).select_related(
            "assignee", "assignee__profile"
        )
        if not form.is_valid():
            return tasks.none()
        filters = form.cleaned_data
        if filters["q"]:
            tasks = tasks.filter(
                Q(title__icontains=filters["q"]) | Q(description__icontains=filters["q"])
            )
        if filters["column"]:
            tasks = tasks.filter(column=filters["column"])
        if filters["priority"]:
            tasks = tasks.filter(priority=filters["priority"])
        if filters["assignee"] == "unassigned":
            tasks = tasks.filter(assignee__isnull=True)
        elif filters["assignee"]:
            tasks = tasks.filter(assignee_id=filters["assignee"])
        if filters["due_from"]:
            tasks = tasks.filter(due_date__gte=filters["due_from"])
        if filters["due_to"]:
            tasks = tasks.filter(due_date__lte=filters["due_to"])

        sort = filters["sort"]
        if sort.startswith("priority_"):
            tasks = tasks.alias(
                priority_rank=Case(
                    When(priority=Task.Priority.LOW, then=0),
                    When(priority=Task.Priority.MEDIUM, then=1),
                    When(priority=Task.Priority.HIGH, then=2),
                )
            )
        ordering = {
            "": ("position", "id"),
            "created_asc": ("created_at", "id"),
            "created_desc": ("-created_at", "id"),
            "due_asc": (F("due_date").asc(nulls_last=True), "id"),
            "due_desc": (F("due_date").desc(nulls_last=True), "id"),
            "priority_asc": ("priority_rank", "id"),
            "priority_desc": ("-priority_rank", "id"),
        }
        return tasks.order_by(*ordering[sort])


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

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        edited_activities = (
            TaskActivity.objects.filter(
                task=self.object,
                event_type=TaskActivity.EventType.COMMENT_EDITED,
            )
            .annotate(
                comment_id=Cast(
                    KeyTextTransform("comment_id", "metadata"),
                    output_field=BigIntegerField(),
                )
            )
            .filter(comment_id=OuterRef("pk"))
        )
        comments = self.object.comments.select_related("author", "author__profile").annotate(
            was_edited=Exists(edited_activities)
        )
        activities = self.object.activities.select_related("actor", "actor__profile")
        context["comment_page"] = Paginator(comments, 20).get_page(
            self.request.GET.get("comments_page")
        )
        context["activity_page"] = Paginator(activities, 30).get_page(
            self.request.GET.get("activity_page")
        )
        context["comment_form"] = TaskCommentForm()
        return context


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


class TaskCommentCreateView(BoardAccessMixin, FormView):
    form_class = TaskCommentForm
    http_method_names = ["post"]

    def check_workspace_permission(self):
        super().check_workspace_permission()
        self.task = self.get_task()

    def form_valid(self, form):
        try:
            create_task_comment(
                task=self.task,
                actor=self.membership,
                **form.cleaned_data,
            )
        except ValidationError as error:
            _service_error(self.request, error)
        else:
            messages.success(self.request, "دیدگاه ثبت شد.")
        return self.get_success_response()

    def form_invalid(self, form):
        messages.error(
            self.request,
            form.errors.get("body", ["متن دیدگاه معتبر نیست."])[0],
        )
        return self.get_success_response()

    def get_success_response(self):
        return redirect(
            "boards:task_detail",
            slug=self.workspace.slug,
            project_id=self.project.pk,
            task_id=self.task.pk,
        )


class TaskCommentAuthorMixin(BoardAccessMixin):
    task = None
    comment = None

    def check_workspace_permission(self):
        super().check_workspace_permission()
        self.task = self.get_task()
        self.comment = self.get_comment(task=self.task)
        if self.comment.author_id != self.request.user.pk:
            raise PermissionDenied

    def archived_response(self):
        messages.error(self.request, "پروژهٔ بایگانی‌شده فقط قابل مشاهده است.")
        return redirect(
            "boards:task_detail",
            slug=self.workspace.slug,
            project_id=self.project.pk,
            task_id=self.task.pk,
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("task", self.task)
        return context


class TaskCommentEditView(TaskCommentAuthorMixin, UpdateView):
    template_name = "boards/comment_form.html"
    form_class = TaskCommentForm
    context_object_name = "comment"
    http_method_names = ["get", "post"]

    def get_object(self, queryset=None):
        return self.comment

    def get(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            return self.archived_response()
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            return self.archived_response()
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        try:
            self.object = update_task_comment(
                comment=self.comment,
                actor=self.membership,
                **form.cleaned_data,
            )
        except ValidationError as error:
            form.add_error(None, error)
            return self.form_invalid(form)
        messages.success(self.request, "دیدگاه ویرایش شد.")
        return redirect(
            "boards:task_detail",
            slug=self.workspace.slug,
            project_id=self.project.pk,
            task_id=self.task.pk,
        )


class TaskCommentDeleteView(TaskCommentAuthorMixin, View):
    template_name = "boards/comment_delete_confirm.html"
    http_method_names = ["get", "post"]

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
                "task": self.task,
                "comment": self.comment,
            },
        )

    def post(self, request, *args, **kwargs):
        if self.project.status == Project.Status.ARCHIVED:
            return self.archived_response()
        try:
            delete_task_comment(comment=self.comment, actor=self.membership)
        except ValidationError as error:
            _service_error(request, error)
        else:
            messages.success(request, "دیدگاه حذف شد.")
        return redirect(
            "boards:task_detail",
            slug=self.workspace.slug,
            project_id=self.project.pk,
            task_id=self.task.pk,
        )
