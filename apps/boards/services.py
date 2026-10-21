from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F

from apps.projects.models import Project
from apps.workspaces.models import WorkspaceMembership

from .models import Board, BoardColumn, Task

POSITION_OFFSET = 1_000_000


def _locked_project_board(*, board_id: int) -> tuple[Project, Board]:
    board_ref = Board.objects.only("project_id").get(pk=board_id)
    project = Project.objects.select_for_update().get(pk=board_ref.project_id)
    board = Board.objects.select_for_update().get(pk=board_id, project=project)
    return project, board


def _locked_actor(*, membership_id: int, workspace_id: int) -> WorkspaceMembership:
    membership = (
        WorkspaceMembership.objects.select_for_update()
        .select_related("user")
        .filter(pk=membership_id, workspace_id=workspace_id)
        .first()
    )
    if not membership:
        raise PermissionDenied
    return membership


def _require_manager(membership: WorkspaceMembership) -> None:
    if membership.role not in {
        WorkspaceMembership.Role.OWNER,
        WorkspaceMembership.Role.ADMIN,
    }:
        raise PermissionDenied


def _require_active(project: Project) -> None:
    if project.status == Project.Status.ARCHIVED:
        raise ValidationError("پروژهٔ بایگانی‌شده فقط قابل مشاهده است.")


def _rewrite_column_positions(board: Board, ordered_columns: list[BoardColumn]) -> None:
    BoardColumn.objects.filter(board=board).update(position=F("position") + POSITION_OFFSET)
    for position, column in enumerate(ordered_columns):
        column.position = position
    BoardColumn.objects.bulk_update(ordered_columns, ["position"])


def _rewrite_task_positions(board: Board, ordered_by_column: dict[int, list[Task]]) -> None:
    Task.objects.filter(
        column__board=board,
        column_id__in=ordered_by_column,
    ).update(position=F("position") + POSITION_OFFSET)
    changed = []
    for column_id, tasks in ordered_by_column.items():
        for position, task in enumerate(tasks):
            task.column_id = column_id
            task.position = position
            changed.append(task)
    Task.objects.bulk_update(changed, ["column", "position"])


def _locked_board_order(board: Board) -> tuple[list[BoardColumn], list[Task]]:
    columns = list(BoardColumn.objects.select_for_update().filter(board=board).order_by("pk"))
    tasks = list(Task.objects.select_for_update().filter(column__board=board).order_by("pk"))
    columns.sort(key=lambda column: (column.position, column.pk))
    tasks.sort(key=lambda task: (task.column_id, task.position, task.pk))
    return columns, tasks


def _apply_task_move(
    *,
    board: Board,
    columns: list[BoardColumn],
    tasks: list[Task],
    task_id: int,
    target_column_id: int,
    target_position: int,
) -> Task:
    task = next((item for item in tasks if item.pk == task_id), None)
    if task is None:
        raise ValidationError("وظیفهٔ موردنظر در این برد پیدا نشد.")
    if target_column_id not in {column.pk for column in columns}:
        raise ValidationError("ستون مقصد در این برد پیدا نشد.")
    ordered_by_column = {
        column.pk: [item for item in tasks if item.column_id == column.pk and item.pk != task.pk]
        for column in columns
    }
    target_tasks = ordered_by_column[target_column_id]
    position = max(0, min(target_position, len(target_tasks)))
    target_tasks.insert(position, task)
    _rewrite_task_positions(board, ordered_by_column)
    task.refresh_from_db()
    return task


@transaction.atomic
def create_column(*, board: Board, actor: WorkspaceMembership, name: str) -> BoardColumn:
    project, board = _locked_project_board(board_id=board.pk)
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_manager(actor)
    _require_active(project)
    columns = list(BoardColumn.objects.select_for_update().filter(board=board))
    column = BoardColumn(board=board, name=name.strip(), position=len(columns))
    column.full_clean()
    column.save()
    return column


@transaction.atomic
def rename_column(*, column: BoardColumn, actor: WorkspaceMembership, name: str) -> BoardColumn:
    project, board = _locked_project_board(board_id=column.board_id)
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_manager(actor)
    _require_active(project)
    column = BoardColumn.objects.select_for_update().get(pk=column.pk, board=board)
    column.name = name.strip()
    column.full_clean()
    column.save(update_fields=["name"])
    return column


@transaction.atomic
def reorder_columns(*, board: Board, actor: WorkspaceMembership, ordered_ids: list[int]) -> None:
    project, board = _locked_project_board(board_id=board.pk)
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_manager(actor)
    _require_active(project)
    columns = list(BoardColumn.objects.select_for_update().filter(board=board))
    by_id = {column.pk: column for column in columns}
    if len(ordered_ids) != len(columns) or set(ordered_ids) != set(by_id):
        raise ValidationError("ترتیب ستون‌ها معتبر نیست.")
    _rewrite_column_positions(board, [by_id[column_id] for column_id in ordered_ids])


@transaction.atomic
def shift_column(
    *,
    column: BoardColumn,
    actor: WorkspaceMembership,
    direction: str,
) -> None:
    project, board = _locked_project_board(board_id=column.board_id)
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_manager(actor)
    _require_active(project)
    columns = list(BoardColumn.objects.select_for_update().filter(board=board).order_by("pk"))
    columns.sort(key=lambda item: (item.position, item.pk))
    column = next((item for item in columns if item.pk == column.pk), None)
    if column is None:
        raise ValidationError("ستون موردنظر پیدا نشد.")
    if direction not in {"up", "down"}:
        raise ValidationError("جهت جابه‌جایی ستون معتبر نیست.")
    index = columns.index(column)
    target = index - 1 if direction == "up" else index + 1
    if 0 <= target < len(columns):
        columns[index], columns[target] = columns[target], columns[index]
        _rewrite_column_positions(board, columns)


@transaction.atomic
def delete_column(*, column: BoardColumn, actor: WorkspaceMembership) -> None:
    project, board = _locked_project_board(board_id=column.board_id)
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_manager(actor)
    _require_active(project)
    columns = list(BoardColumn.objects.select_for_update().filter(board=board))
    column = next((item for item in columns if item.pk == column.pk), None)
    if column is None:
        raise ValidationError("ستون موردنظر پیدا نشد.")
    if len(columns) == 1:
        raise ValidationError("آخرین ستون برد قابل حذف نیست.")
    if Task.objects.select_for_update().filter(column=column).exists():
        raise ValidationError("برای حذف ستون، ابتدا وظیفه‌های آن را جابه‌جا کنید.")
    column.delete()
    _rewrite_column_positions(board, [item for item in columns if item.pk != column.pk])


def _validate_assignee(*, workspace_id: int, assignee_id: int | None) -> None:
    if (
        assignee_id
        and not WorkspaceMembership.objects.filter(
            workspace_id=workspace_id,
            user_id=assignee_id,
        ).exists()
    ):
        raise ValidationError({"assignee": "مسئول باید عضو همین فضای کاری باشد."})


@transaction.atomic
def create_task(
    *,
    column: BoardColumn,
    actor: WorkspaceMembership,
    title: str,
    description: str,
    priority: str,
    due_date,
    assignee,
) -> Task:
    project, board = _locked_project_board(board_id=column.board_id)
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_active(project)
    column = BoardColumn.objects.select_for_update().get(pk=column.pk, board=board)
    position = Task.objects.select_for_update().filter(column=column).count()
    _validate_assignee(
        workspace_id=project.workspace_id,
        assignee_id=assignee.pk if assignee else None,
    )
    task = Task(
        column=column,
        title=title.strip(),
        description=description,
        priority=priority,
        due_date=due_date,
        assignee=assignee,
        creator=actor.user,
        position=position,
    )
    task.full_clean()
    task.save()
    return task


@transaction.atomic
def update_task(
    *,
    task: Task,
    actor: WorkspaceMembership,
    title: str,
    description: str,
    priority: str,
    due_date,
    assignee,
) -> Task:
    project, board = _locked_project_board(board_id=task.column.board_id)
    _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_active(project)
    task = Task.objects.select_for_update().get(pk=task.pk, column__board=board)
    _validate_assignee(
        workspace_id=project.workspace_id,
        assignee_id=assignee.pk if assignee else None,
    )
    task.title = title.strip()
    task.description = description
    task.priority = priority
    task.due_date = due_date
    task.assignee = assignee
    task.full_clean()
    task.save(
        update_fields=[
            "title",
            "description",
            "priority",
            "due_date",
            "assignee",
            "updated_at",
        ]
    )
    return task


@transaction.atomic
def delete_task(*, task: Task, actor: WorkspaceMembership) -> None:
    project, board = _locked_project_board(board_id=task.column.board_id)
    _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_active(project)
    task = Task.objects.select_for_update().get(pk=task.pk, column__board=board)
    source_column_id = task.column_id
    task.delete()
    remaining = list(
        Task.objects.select_for_update()
        .filter(column_id=source_column_id)
        .order_by("position", "id")
    )
    _rewrite_task_positions(board, {source_column_id: remaining})


@transaction.atomic
def move_task(
    *,
    task: Task,
    actor: WorkspaceMembership,
    target_column: BoardColumn,
    target_position: int,
) -> Task:
    project, board = _locked_project_board(board_id=task.column.board_id)
    _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_active(project)
    columns, tasks = _locked_board_order(board)
    return _apply_task_move(
        board=board,
        columns=columns,
        tasks=tasks,
        task_id=task.pk,
        target_column_id=target_column.pk,
        target_position=target_position,
    )


@transaction.atomic
def nudge_task(
    *,
    task: Task,
    actor: WorkspaceMembership,
    direction: str,
) -> Task:
    project, board = _locked_project_board(board_id=task.column.board_id)
    _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_active(project)
    columns, tasks = _locked_board_order(board)
    task = next((item for item in tasks if item.pk == task.pk), None)
    if task is None:
        raise ValidationError("وظیفهٔ موردنظر در این برد پیدا نشد.")
    if direction not in {"up", "down", "previous", "next"}:
        raise ValidationError("جهت جابه‌جایی وظیفه معتبر نیست.")
    column_index = next(
        index for index, column in enumerate(columns) if column.pk == task.column_id
    )
    target_column_id = task.column_id
    target_position = task.position
    if direction == "up":
        target_position -= 1
    elif direction == "down":
        target_position += 1
    elif direction == "previous" and column_index > 0:
        target_column_id = columns[column_index - 1].pk
        target_position = sum(
            item.column_id == target_column_id and item.pk != task.pk for item in tasks
        )
    elif direction == "next" and column_index < len(columns) - 1:
        target_column_id = columns[column_index + 1].pk
        target_position = sum(
            item.column_id == target_column_id and item.pk != task.pk for item in tasks
        )
    return _apply_task_move(
        board=board,
        columns=columns,
        tasks=tasks,
        task_id=task.pk,
        target_column_id=target_column_id,
        target_position=target_position,
    )
