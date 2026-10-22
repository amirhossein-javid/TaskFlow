from django.shortcuts import get_object_or_404

from apps.projects.mixins import ProjectAccessMixin
from apps.workspaces.permissions import require_manager

from .models import BoardColumn, Task, TaskComment


class BoardAccessMixin(ProjectAccessMixin):
    """Resolve the project's board and provide scoped child lookups."""

    board = None

    def check_workspace_permission(self):
        super().check_workspace_permission()
        self.board = self.project.board

    def get_column(self, column_id=None):
        return get_object_or_404(
            BoardColumn,
            pk=column_id or self.kwargs["column_id"],
            board=self.board,
        )

    def get_task(self, task_id=None):
        return get_object_or_404(
            Task.objects.select_related(
                "column",
                "assignee",
                "assignee__profile",
                "creator",
                "creator__profile",
            ),
            pk=task_id or self.kwargs["task_id"],
            column__board=self.board,
        )

    def get_comment(self, comment_id=None, task=None):
        queryset = TaskComment.objects.select_related(
            "task",
            "task__column",
            "author",
            "author__profile",
        ).filter(task__column__board=self.board)
        if task is not None:
            queryset = queryset.filter(task=task)
        return get_object_or_404(
            queryset,
            pk=comment_id or self.kwargs["comment_id"],
        )

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.setdefault("board", self.board)
        return context


class BoardManagerRequiredMixin(BoardAccessMixin):
    def check_workspace_permission(self):
        super().check_workspace_permission()
        require_manager(self.membership)
