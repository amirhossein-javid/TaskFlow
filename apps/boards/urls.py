from django.urls import path

from .checklist_views import (
    ChecklistDeleteView,
    ChecklistEditView,
    ChecklistItemEditView,
    ChecklistItemStateView,
)
from .label_views import LabelDeleteView, LabelEditView, LabelListView, TaskLabelView
from .views import (
    BoardDetailView,
    ColumnCreateView,
    ColumnDeleteView,
    ColumnRenameView,
    ColumnReorderView,
    ColumnShiftView,
    TaskCommentCreateView,
    TaskCommentDeleteView,
    TaskCommentEditView,
    TaskCreateView,
    TaskDeleteView,
    TaskDetailView,
    TaskEditView,
    TaskMoveView,
    TaskNudgeView,
)

app_name = "boards"

urlpatterns = [
    path(
        "tasks/<int:task_id>/checklists/new/", ChecklistEditView.as_view(), name="checklist_create"
    ),
    path(
        "tasks/<int:task_id>/checklists/<int:checklist_id>/edit/",
        ChecklistEditView.as_view(),
        name="checklist_edit",
    ),
    path(
        "tasks/<int:task_id>/checklists/<int:checklist_id>/delete/",
        ChecklistDeleteView.as_view(),
        name="checklist_delete",
    ),
    path(
        "tasks/<int:task_id>/checklists/<int:checklist_id>/items/new/",
        ChecklistItemEditView.as_view(),
        name="checklist_item_create",
    ),
    path(
        "tasks/<int:task_id>/checklists/<int:checklist_id>/items/<int:item_id>/edit/",
        ChecklistItemEditView.as_view(),
        name="checklist_item_edit",
    ),
    path(
        "tasks/<int:task_id>/checklists/<int:checklist_id>/items/<int:item_id>/delete/",
        ChecklistDeleteView.as_view(),
        name="checklist_item_delete",
    ),
    path(
        "tasks/<int:task_id>/checklists/<int:checklist_id>/items/<int:item_id>/state/",
        ChecklistItemStateView.as_view(),
        name="checklist_item_state",
    ),
    path("labels/", LabelListView.as_view(), name="label_list"),
    path("labels/new/", LabelEditView.as_view(), name="label_create"),
    path("labels/<int:label_id>/edit/", LabelEditView.as_view(), name="label_edit"),
    path("labels/<int:label_id>/delete/", LabelDeleteView.as_view(), name="label_delete"),
    path("tasks/<int:task_id>/labels/", TaskLabelView.as_view(), name="task_label"),
    path("", BoardDetailView.as_view(), name="detail"),
    path("columns/new/", ColumnCreateView.as_view(), name="column_create"),
    path("columns/reorder/", ColumnReorderView.as_view(), name="column_reorder"),
    path("columns/<int:column_id>/rename/", ColumnRenameView.as_view(), name="column_rename"),
    path("columns/<int:column_id>/shift/", ColumnShiftView.as_view(), name="column_shift"),
    path("columns/<int:column_id>/delete/", ColumnDeleteView.as_view(), name="column_delete"),
    path("columns/<int:column_id>/tasks/new/", TaskCreateView.as_view(), name="task_create"),
    path("tasks/<int:task_id>/", TaskDetailView.as_view(), name="task_detail"),
    path("tasks/<int:task_id>/edit/", TaskEditView.as_view(), name="task_edit"),
    path("tasks/<int:task_id>/delete/", TaskDeleteView.as_view(), name="task_delete"),
    path("tasks/<int:task_id>/move/", TaskMoveView.as_view(), name="task_move"),
    path("tasks/<int:task_id>/nudge/", TaskNudgeView.as_view(), name="task_nudge"),
    path(
        "tasks/<int:task_id>/comments/new/",
        TaskCommentCreateView.as_view(),
        name="comment_create",
    ),
    path(
        "tasks/<int:task_id>/comments/<int:comment_id>/edit/",
        TaskCommentEditView.as_view(),
        name="comment_edit",
    ),
    path(
        "tasks/<int:task_id>/comments/<int:comment_id>/delete/",
        TaskCommentDeleteView.as_view(),
        name="comment_delete",
    ),
]
