from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import F

from apps.notifications.models import Notification
from apps.notifications.services import notify_task_assignee
from apps.projects.models import Project
from apps.workspaces.models import WorkspaceMembership

from .models import (
    Board,
    BoardColumn,
    ChecklistItem,
    ProjectLabel,
    Task,
    TaskActivity,
    TaskChecklist,
    TaskComment,
    TaskLabel,
)

POSITION_OFFSET = 1_000_000


def _locked_checklist(*, checklist_id, task):
    checklist = TaskChecklist.objects.select_for_update().filter(pk=checklist_id, task=task).first()
    if checklist is None:
        raise ValidationError("چک‌لیست موردنظر پیدا نشد.")
    return checklist


def _locked_checklist_item(*, item_id, checklist):
    item = ChecklistItem.objects.select_for_update().filter(pk=item_id, checklist=checklist).first()
    if item is None:
        raise ValidationError("مورد چک‌لیست پیدا نشد.")
    return item


@transaction.atomic
def create_checklist(*, task: Task, actor: WorkspaceMembership, title: str):
    project, task, actor = _locked_task_context(task=task, actor=actor)
    checklist = TaskChecklist(task=task, title=title.strip())
    checklist.full_clean()
    checklist.save()
    _record_task_activity(
        project=project,
        task=task,
        actor=actor,
        event_type=TaskActivity.EventType.CHECKLIST_CREATED,
        metadata={"checklist_id": checklist.pk, "checklist_title": checklist.title},
    )
    return checklist


@transaction.atomic
def update_checklist(*, checklist: TaskChecklist, actor: WorkspaceMembership, title: str):
    project, task, actor = _locked_task_context(task=checklist.task, actor=actor)
    checklist = _locked_checklist(checklist_id=checklist.pk, task=task)
    title = title.strip()
    if checklist.title == title:
        return checklist
    previous = checklist.title
    checklist.title = title
    checklist.full_clean()
    checklist.save(update_fields=["title"])
    _record_task_activity(
        project=project,
        task=task,
        actor=actor,
        event_type=TaskActivity.EventType.CHECKLIST_UPDATED,
        metadata={
            "checklist_id": checklist.pk,
            "checklist_title": title,
            "previous_title": previous,
        },
    )
    return checklist


@transaction.atomic
def delete_checklist(*, checklist: TaskChecklist, actor: WorkspaceMembership):
    project, task, actor = _locked_task_context(task=checklist.task, actor=actor)
    checklist = _locked_checklist(checklist_id=checklist.pk, task=task)
    _record_task_activity(
        project=project,
        task=task,
        actor=actor,
        event_type=TaskActivity.EventType.CHECKLIST_DELETED,
        metadata={
            "checklist_id": checklist.pk,
            "checklist_title": checklist.title,
            "item_count": checklist.items.count(),
        },
    )
    checklist.delete()


@transaction.atomic
def create_checklist_item(*, checklist: TaskChecklist, actor: WorkspaceMembership, text: str):
    project, task, actor = _locked_task_context(task=checklist.task, actor=actor)
    checklist = _locked_checklist(checklist_id=checklist.pk, task=task)
    item = ChecklistItem(checklist=checklist, text=text.strip())
    item.full_clean()
    item.save()
    _record_task_activity(
        project=project,
        task=task,
        actor=actor,
        event_type=TaskActivity.EventType.ITEM_CREATED,
        metadata={
            "checklist_id": checklist.pk,
            "checklist_title": checklist.title,
            "item_id": item.pk,
            "item_text": item.text,
        },
    )
    return item


@transaction.atomic
def update_checklist_item(*, item: ChecklistItem, actor: WorkspaceMembership, text: str):
    project, task, actor = _locked_task_context(task=item.checklist.task, actor=actor)
    checklist = _locked_checklist(checklist_id=item.checklist_id, task=task)
    item = _locked_checklist_item(item_id=item.pk, checklist=checklist)
    text = text.strip()
    if item.text == text:
        return item
    previous = item.text
    item.text = text
    item.full_clean()
    item.save(update_fields=["text"])
    _record_task_activity(
        project=project,
        task=task,
        actor=actor,
        event_type=TaskActivity.EventType.ITEM_UPDATED,
        metadata={
            "checklist_id": checklist.pk,
            "checklist_title": checklist.title,
            "item_id": item.pk,
            "item_text": text,
            "previous_text": previous,
        },
    )
    return item


@transaction.atomic
def set_checklist_item_completed(
    *, item: ChecklistItem, actor: WorkspaceMembership, completed: bool
):
    if not isinstance(completed, bool):
        raise ValidationError("وضعیت مورد معتبر نیست.")
    project, task, actor = _locked_task_context(task=item.checklist.task, actor=actor)
    checklist = _locked_checklist(checklist_id=item.checklist_id, task=task)
    item = _locked_checklist_item(item_id=item.pk, checklist=checklist)
    if item.is_completed == completed:
        return item
    item.is_completed = completed
    item.save(update_fields=["is_completed"])
    _record_task_activity(
        project=project,
        task=task,
        actor=actor,
        event_type=(
            TaskActivity.EventType.ITEM_COMPLETED
            if completed
            else TaskActivity.EventType.ITEM_REOPENED
        ),
        metadata={
            "checklist_id": checklist.pk,
            "checklist_title": checklist.title,
            "item_id": item.pk,
            "item_text": item.text,
            "is_completed": completed,
        },
    )
    return item


@transaction.atomic
def delete_checklist_item(*, item: ChecklistItem, actor: WorkspaceMembership):
    project, task, actor = _locked_task_context(task=item.checklist.task, actor=actor)
    checklist = _locked_checklist(checklist_id=item.checklist_id, task=task)
    item = _locked_checklist_item(item_id=item.pk, checklist=checklist)
    _record_task_activity(
        project=project,
        task=task,
        actor=actor,
        event_type=TaskActivity.EventType.ITEM_DELETED,
        metadata={
            "checklist_id": checklist.pk,
            "checklist_title": checklist.title,
            "item_id": item.pk,
            "item_text": item.text,
        },
    )
    item.delete()


@transaction.atomic
def create_project_label(*, board: Board, actor: WorkspaceMembership, name: str, color: str):
    project, board = _locked_project_board(board_id=board.pk)
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_manager(actor)
    _require_active(project)
    label = ProjectLabel(project=project, name=name.strip(), color=color)
    label.full_clean()
    label.save()
    return label


@transaction.atomic
def update_project_label(*, label: ProjectLabel, actor: WorkspaceMembership, name: str, color: str):
    project, board = _locked_project_board(board_id=label.project.board.pk)
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_manager(actor)
    _require_active(project)
    label = ProjectLabel.objects.select_for_update().filter(pk=label.pk, project=project).first()
    if label is None:
        raise ValidationError("برچسب موردنظر پیدا نشد.")
    if (label.name, label.color) != (name.strip(), color):
        label.name, label.color = name.strip(), color
        label.full_clean()
        label.save(update_fields=["name", "color"])
    return label


@transaction.atomic
def delete_project_label(*, label: ProjectLabel, actor: WorkspaceMembership):
    project, board = _locked_project_board(board_id=label.project.board.pk)
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_manager(actor)
    _require_active(project)
    label = ProjectLabel.objects.select_for_update().filter(pk=label.pk, project=project).first()
    if label is None:
        raise ValidationError("برچسب موردنظر پیدا نشد.")
    label.delete()


def _locked_task_context(*, task: Task, actor: WorkspaceMembership):
    project, board = _locked_project_board(board_id=task.column.board_id)
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_active(project)
    task = (
        Task.objects.select_for_update(of=("self",)).filter(pk=task.pk, column__board=board).first()
    )
    if task is None:
        raise ValidationError("وظیفهٔ موردنظر پیدا نشد.")
    return project, task, actor


@transaction.atomic
def set_task_label(*, task: Task, label: ProjectLabel, actor: WorkspaceMembership, attached: bool):
    project, task, actor = _locked_task_context(task=task, actor=actor)
    if not isinstance(attached, bool):
        raise ValidationError("وضعیت برچسب معتبر نیست.")
    label = ProjectLabel.objects.select_for_update().filter(pk=label.pk, project=project).first()
    if label is None:
        raise ValidationError("برچسب باید متعلق به پروژهٔ همین وظیفه باشد.")
    if attached:
        _, changed = TaskLabel.objects.get_or_create(task=task, label=label)
    else:
        changed, _ = TaskLabel.objects.filter(task=task, label=label).delete()
    if changed:
        _record_task_activity(
            project=project,
            task=task,
            actor=actor,
            event_type=(
                TaskActivity.EventType.LABEL_ATTACHED
                if attached
                else TaskActivity.EventType.LABEL_DETACHED
            ),
            metadata={"label_id": label.pk, "label_name": label.name, "label_color": label.color},
        )


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


def _record_task_activity(
    *,
    project: Project,
    task: Task,
    actor: WorkspaceMembership,
    event_type: str,
    metadata: dict | None = None,
) -> TaskActivity:
    return TaskActivity.objects.create(
        project=project,
        task=task,
        actor=actor.user,
        event_type=event_type,
        task_title=task.title,
        metadata=metadata or {},
    )


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


def _locked_comment_task(*, task_id: int, board: Board) -> Task:
    task = Task.objects.select_for_update().filter(pk=task_id, column__board=board).first()
    if task is None:
        raise ValidationError("وظیفهٔ مربوط به دیدگاه دیگر وجود ندارد.")
    return task


def _locked_comment(*, comment_id: int, task: Task) -> TaskComment:
    comment = TaskComment.objects.select_for_update().filter(pk=comment_id, task=task).first()
    if comment is None:
        raise ValidationError("دیدگاه موردنظر دیگر وجود ندارد.")
    return comment


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
    activity = _record_task_activity(
        project=project,
        task=task,
        actor=actor,
        event_type=TaskActivity.EventType.TASK_CREATED,
        metadata={"column_id": column.pk, "column_name": column.name},
    )
    notify_task_assignee(task=task, activity=activity, kind=Notification.Kind.ASSIGNMENT)
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
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_active(project)
    task = Task.objects.select_for_update().get(pk=task.pk, column__board=board)
    _validate_assignee(
        workspace_id=project.workspace_id,
        assignee_id=assignee.pk if assignee else None,
    )
    normalized_title = title.strip()
    normalized_assignee_id = assignee.pk if assignee else None
    changed_fields = []
    for field_name, value in {
        "title": normalized_title,
        "description": description,
        "priority": priority,
        "due_date": due_date,
    }.items():
        if getattr(task, field_name) != value:
            changed_fields.append(field_name)
    assignee_changed = task.assignee_id != normalized_assignee_id
    if not changed_fields and not assignee_changed:
        return task
    task.title = normalized_title
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
    if changed_fields:
        _record_task_activity(
            project=project,
            task=task,
            actor=actor,
            event_type=TaskActivity.EventType.TASK_UPDATED,
            metadata={"changed_fields": changed_fields},
        )
    if assignee_changed:
        activity = _record_task_activity(
            project=project,
            task=task,
            actor=actor,
            event_type=TaskActivity.EventType.ASSIGNEE_CHANGED,
            metadata={"assignee_id": normalized_assignee_id},
        )
        notify_task_assignee(task=task, activity=activity, kind=Notification.Kind.ASSIGNMENT)
    return task


@transaction.atomic
def delete_task(*, task: Task, actor: WorkspaceMembership) -> None:
    project, board = _locked_project_board(board_id=task.column.board_id)
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_active(project)
    task = Task.objects.select_for_update().get(pk=task.pk, column__board=board)
    source_column_id = task.column_id
    _record_task_activity(
        project=project,
        task=task,
        actor=actor,
        event_type=TaskActivity.EventType.TASK_DELETED,
        metadata={"column_id": source_column_id},
    )
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
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_active(project)
    columns, tasks = _locked_board_order(board)
    locked_task = next((item for item in tasks if item.pk == task.pk), None)
    if locked_task is None:
        raise ValidationError("وظیفهٔ موردنظر در این برد پیدا نشد.")
    source_column_id = locked_task.column_id
    source_position = locked_task.position
    column_names = {column.pk: column.name for column in columns}
    moved_task = _apply_task_move(
        board=board,
        columns=columns,
        tasks=tasks,
        task_id=task.pk,
        target_column_id=target_column.pk,
        target_position=target_position,
    )
    if (source_column_id, source_position) != (moved_task.column_id, moved_task.position):
        activity = _record_task_activity(
            project=project,
            task=moved_task,
            actor=actor,
            event_type=TaskActivity.EventType.TASK_MOVED,
            metadata={
                "from_column_id": source_column_id,
                "from_column_name": column_names[source_column_id],
                "from_position": source_position,
                "to_column_id": moved_task.column_id,
                "to_column_name": column_names[moved_task.column_id],
                "to_position": moved_task.position,
            },
        )
        if source_column_id != moved_task.column_id:
            notify_task_assignee(
                task=moved_task, activity=activity, kind=Notification.Kind.COLUMN_CHANGE
            )
    return moved_task


@transaction.atomic
def nudge_task(
    *,
    task: Task,
    actor: WorkspaceMembership,
    direction: str,
) -> Task:
    project, board = _locked_project_board(board_id=task.column.board_id)
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
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
    source_column_id = task.column_id
    source_position = task.position
    column_names = {column.pk: column.name for column in columns}
    moved_task = _apply_task_move(
        board=board,
        columns=columns,
        tasks=tasks,
        task_id=task.pk,
        target_column_id=target_column_id,
        target_position=target_position,
    )
    if (source_column_id, source_position) != (moved_task.column_id, moved_task.position):
        activity = _record_task_activity(
            project=project,
            task=moved_task,
            actor=actor,
            event_type=TaskActivity.EventType.TASK_MOVED,
            metadata={
                "from_column_id": source_column_id,
                "from_column_name": column_names[source_column_id],
                "from_position": source_position,
                "to_column_id": moved_task.column_id,
                "to_column_name": column_names[moved_task.column_id],
                "to_position": moved_task.position,
            },
        )
        if source_column_id != moved_task.column_id:
            notify_task_assignee(
                task=moved_task, activity=activity, kind=Notification.Kind.COLUMN_CHANGE
            )
    return moved_task


@transaction.atomic
def create_task_comment(
    *,
    task: Task,
    actor: WorkspaceMembership,
    body: str,
) -> TaskComment:
    project, board = _locked_project_board(board_id=task.column.board_id)
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_active(project)
    task = _locked_comment_task(task_id=task.pk, board=board)
    comment = TaskComment(task=task, author=actor.user, body=body.strip())
    comment.full_clean()
    comment.save()
    activity = _record_task_activity(
        project=project,
        task=task,
        actor=actor,
        event_type=TaskActivity.EventType.COMMENT_CREATED,
        metadata={"comment_id": comment.pk},
    )
    notify_task_assignee(task=task, activity=activity, kind=Notification.Kind.COMMENT)
    return comment


@transaction.atomic
def update_task_comment(
    *,
    comment: TaskComment,
    actor: WorkspaceMembership,
    body: str,
) -> TaskComment:
    project, board = _locked_project_board(board_id=comment.task.column.board_id)
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_active(project)
    task = _locked_comment_task(task_id=comment.task_id, board=board)
    comment = _locked_comment(comment_id=comment.pk, task=task)
    if comment.author_id != actor.user_id:
        raise PermissionDenied
    normalized_body = body.strip()
    if comment.body == normalized_body:
        return comment
    comment.body = normalized_body
    comment.full_clean()
    comment.save(update_fields=["body", "updated_at"])
    _record_task_activity(
        project=project,
        task=task,
        actor=actor,
        event_type=TaskActivity.EventType.COMMENT_EDITED,
        metadata={"comment_id": comment.pk},
    )
    return comment


@transaction.atomic
def delete_task_comment(
    *,
    comment: TaskComment,
    actor: WorkspaceMembership,
) -> None:
    project, board = _locked_project_board(board_id=comment.task.column.board_id)
    actor = _locked_actor(membership_id=actor.pk, workspace_id=project.workspace_id)
    _require_active(project)
    task = _locked_comment_task(task_id=comment.task_id, board=board)
    comment = _locked_comment(comment_id=comment.pk, task=task)
    if comment.author_id != actor.user_id:
        raise PermissionDenied
    comment_id = comment.pk
    comment.delete()
    _record_task_activity(
        project=project,
        task=task,
        actor=actor,
        event_type=TaskActivity.EventType.COMMENT_DELETED,
        metadata={"comment_id": comment_id},
    )
