from django.urls import path

from . import views

app_name = "boards"

urlpatterns = [
    path("", views.board_detail, name="detail"),
    path("columns/new/", views.column_create, name="column_create"),
    path("columns/reorder/", views.column_reorder, name="column_reorder"),
    path("columns/<int:column_id>/rename/", views.column_rename, name="column_rename"),
    path("columns/<int:column_id>/shift/", views.column_shift, name="column_shift"),
    path("columns/<int:column_id>/delete/", views.column_delete, name="column_delete"),
    path("columns/<int:column_id>/tasks/new/", views.task_create, name="task_create"),
    path("tasks/<int:task_id>/", views.task_detail, name="task_detail"),
    path("tasks/<int:task_id>/edit/", views.task_edit, name="task_edit"),
    path("tasks/<int:task_id>/delete/", views.task_delete, name="task_delete"),
    path("tasks/<int:task_id>/move/", views.task_move, name="task_move"),
    path("tasks/<int:task_id>/nudge/", views.task_nudge, name="task_nudge"),
]
