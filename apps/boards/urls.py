from django.urls import path

from .views import (
    BoardDetailView,
    ColumnCreateView,
    ColumnDeleteView,
    ColumnRenameView,
    ColumnReorderView,
    ColumnShiftView,
    TaskCreateView,
    TaskDeleteView,
    TaskDetailView,
    TaskEditView,
    TaskMoveView,
    TaskNudgeView,
)

app_name = "boards"

urlpatterns = [
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
]
