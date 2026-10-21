import json

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.exceptions import ValidationError
from django.http import JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.http import require_http_methods, require_POST

from apps.projects.models import Project
from apps.projects.permissions import get_project_for_member
from apps.workspaces.models import WorkspaceMembership
from apps.workspaces.permissions import require_manager

from .forms import BoardColumnForm, TaskForm
from .models import BoardColumn, Task
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


def _board_context(*, user, slug: str, project_id: int):
    workspace, membership, project = get_project_for_member(
        user=user,
        slug=slug,
        project_id=project_id,
    )
    return workspace, membership, project, project.board


def _redirect_to_board(workspace, project):
    return redirect("boards:detail", slug=workspace.slug, project_id=project.pk)


def _service_error(request, error: ValidationError) -> None:
    messages.error(request, error.messages[0])


@login_required
def board_detail(request, slug, project_id):
    workspace, membership, project, board = _board_context(
        user=request.user,
        slug=slug,
        project_id=project_id,
    )
    columns = board.columns.prefetch_related(
        "tasks__assignee",
        "tasks__assignee__profile",
    )
    return render(
        request,
        "boards/board_detail.html",
        {
            "workspace": workspace,
            "membership": membership,
            "project": project,
            "board": board,
            "columns": columns,
            "column_form": BoardColumnForm(),
            "is_manager": membership.role
            in {WorkspaceMembership.Role.OWNER, WorkspaceMembership.Role.ADMIN},
        },
    )


@login_required
@require_POST
def column_create(request, slug, project_id):
    workspace, membership, project, board = _board_context(
        user=request.user, slug=slug, project_id=project_id
    )
    require_manager(membership)
    form = BoardColumnForm(request.POST)
    if form.is_valid():
        try:
            create_column(board=board, actor=membership, **form.cleaned_data)
        except ValidationError as error:
            _service_error(request, error)
        else:
            messages.success(request, "ستون جدید ساخته شد.")
    else:
        messages.error(request, form.errors.get("name", ["نام ستون معتبر نیست."])[0])
    return _redirect_to_board(workspace, project)


@login_required
@require_POST
def column_rename(request, slug, project_id, column_id):
    workspace, membership, project, board = _board_context(
        user=request.user, slug=slug, project_id=project_id
    )
    require_manager(membership)
    column = get_object_or_404(BoardColumn, pk=column_id, board=board)
    form = BoardColumnForm(request.POST, instance=column)
    if form.is_valid():
        try:
            rename_column(column=column, actor=membership, **form.cleaned_data)
        except ValidationError as error:
            _service_error(request, error)
        else:
            messages.success(request, "نام ستون تغییر کرد.")
    else:
        messages.error(request, form.errors.get("name", ["نام ستون معتبر نیست."])[0])
    return _redirect_to_board(workspace, project)


@login_required
@require_POST
def column_reorder(request, slug, project_id):
    workspace, membership, project, board = _board_context(
        user=request.user, slug=slug, project_id=project_id
    )
    require_manager(membership)
    try:
        payload = json.loads(request.body)
        ordered_ids = [int(column_id) for column_id in payload["columns"]]
        reorder_columns(board=board, actor=membership, ordered_ids=ordered_ids)
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "درخواست نامعتبر است."}, status=400)
    except ValidationError as error:
        return JsonResponse({"error": error.messages[0]}, status=400)
    return JsonResponse({"ok": True})


@login_required
@require_POST
def column_shift(request, slug, project_id, column_id):
    workspace, membership, project, board = _board_context(
        user=request.user, slug=slug, project_id=project_id
    )
    require_manager(membership)
    column = get_object_or_404(BoardColumn, pk=column_id, board=board)
    try:
        shift_column(
            column=column,
            actor=membership,
            direction=request.POST.get("direction", ""),
        )
    except ValidationError as error:
        _service_error(request, error)
    return _redirect_to_board(workspace, project)


@login_required
@require_http_methods(["GET", "POST"])
def column_delete(request, slug, project_id, column_id):
    workspace, membership, project, board = _board_context(
        user=request.user, slug=slug, project_id=project_id
    )
    require_manager(membership)
    column = get_object_or_404(BoardColumn, pk=column_id, board=board)
    if request.method == "POST":
        try:
            delete_column(column=column, actor=membership)
        except ValidationError as error:
            _service_error(request, error)
        else:
            messages.success(request, "ستون حذف شد.")
        return _redirect_to_board(workspace, project)
    return render(
        request,
        "boards/column_delete_confirm.html",
        {
            "workspace": workspace,
            "membership": membership,
            "project": project,
            "column": column,
        },
    )


def _task_for_board(*, board, task_id: int) -> Task:
    return get_object_or_404(
        Task.objects.select_related(
            "column",
            "assignee",
            "assignee__profile",
            "creator",
            "creator__profile",
        ),
        pk=task_id,
        column__board=board,
    )


@login_required
@require_http_methods(["GET", "POST"])
def task_create(request, slug, project_id, column_id):
    workspace, membership, project, board = _board_context(
        user=request.user, slug=slug, project_id=project_id
    )
    column = get_object_or_404(BoardColumn, pk=column_id, board=board)
    if project.status == Project.Status.ARCHIVED:
        messages.error(request, "پروژهٔ بایگانی‌شده فقط قابل مشاهده است.")
        return _redirect_to_board(workspace, project)
    form = TaskForm(
        request.POST or None,
        instance=Task(column=column),
        workspace=workspace,
    )
    if request.method == "POST" and form.is_valid():
        try:
            task = create_task(column=column, actor=membership, **form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "وظیفه ساخته شد.")
            return redirect(
                "boards:task_detail",
                slug=workspace.slug,
                project_id=project.pk,
                task_id=task.pk,
            )
    return render(
        request,
        "boards/task_form.html",
        {
            "workspace": workspace,
            "membership": membership,
            "project": project,
            "column": column,
            "task": None,
            "form": form,
        },
    )


@login_required
def task_detail(request, slug, project_id, task_id):
    workspace, membership, project, board = _board_context(
        user=request.user, slug=slug, project_id=project_id
    )
    task = _task_for_board(board=board, task_id=task_id)
    return render(
        request,
        "boards/task_detail.html",
        {
            "workspace": workspace,
            "membership": membership,
            "project": project,
            "task": task,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def task_edit(request, slug, project_id, task_id):
    workspace, membership, project, board = _board_context(
        user=request.user, slug=slug, project_id=project_id
    )
    task = _task_for_board(board=board, task_id=task_id)
    if project.status == Project.Status.ARCHIVED:
        messages.error(request, "پروژهٔ بایگانی‌شده فقط قابل مشاهده است.")
        return redirect(
            "boards:task_detail",
            slug=workspace.slug,
            project_id=project.pk,
            task_id=task.pk,
        )
    form = TaskForm(request.POST or None, instance=task, workspace=workspace)
    if request.method == "POST" and form.is_valid():
        try:
            task = update_task(task=task, actor=membership, **form.cleaned_data)
        except ValidationError as error:
            form.add_error(None, error)
        else:
            messages.success(request, "وظیفه به‌روزرسانی شد.")
            return redirect(
                "boards:task_detail",
                slug=workspace.slug,
                project_id=project.pk,
                task_id=task.pk,
            )
    return render(
        request,
        "boards/task_form.html",
        {
            "workspace": workspace,
            "membership": membership,
            "project": project,
            "column": task.column,
            "task": task,
            "form": form,
        },
    )


@login_required
@require_http_methods(["GET", "POST"])
def task_delete(request, slug, project_id, task_id):
    workspace, membership, project, board = _board_context(
        user=request.user, slug=slug, project_id=project_id
    )
    task = _task_for_board(board=board, task_id=task_id)
    if project.status == Project.Status.ARCHIVED:
        messages.error(request, "پروژهٔ بایگانی‌شده فقط قابل مشاهده است.")
        return redirect(
            "boards:task_detail",
            slug=workspace.slug,
            project_id=project.pk,
            task_id=task.pk,
        )
    if request.method == "POST":
        try:
            delete_task(task=task, actor=membership)
        except ValidationError as error:
            _service_error(request, error)
        else:
            messages.success(request, "وظیفه حذف شد.")
        return _redirect_to_board(workspace, project)
    return render(
        request,
        "boards/task_delete_confirm.html",
        {
            "workspace": workspace,
            "membership": membership,
            "project": project,
            "task": task,
        },
    )


@login_required
@require_POST
def task_move(request, slug, project_id, task_id):
    workspace, membership, project, board = _board_context(
        user=request.user, slug=slug, project_id=project_id
    )
    task = _task_for_board(board=board, task_id=task_id)
    try:
        payload = json.loads(request.body)
        target_column = get_object_or_404(
            BoardColumn,
            pk=int(payload["column"]),
            board=board,
        )
        target_position = int(payload["position"])
        task = move_task(
            task=task,
            actor=membership,
            target_column=target_column,
            target_position=target_position,
        )
    except (KeyError, TypeError, ValueError, json.JSONDecodeError):
        return JsonResponse({"error": "درخواست جابه‌جایی معتبر نیست."}, status=400)
    except ValidationError as error:
        return JsonResponse({"error": error.messages[0]}, status=400)
    return JsonResponse({"ok": True, "column": task.column_id, "position": task.position})


@login_required
@require_POST
def task_nudge(request, slug, project_id, task_id):
    workspace, membership, project, board = _board_context(
        user=request.user, slug=slug, project_id=project_id
    )
    task = _task_for_board(board=board, task_id=task_id)
    try:
        nudge_task(
            task=task,
            actor=membership,
            direction=request.POST.get("direction", ""),
        )
    except ValidationError as error:
        _service_error(request, error)
    return _redirect_to_board(workspace, project)
