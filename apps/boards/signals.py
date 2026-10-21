from django.db import transaction
from django.db.models.signals import post_save
from django.dispatch import receiver

from apps.projects.models import Project

from .models import Board, BoardColumn

DEFAULT_COLUMN_NAMES = ("برای انجام", "در حال انجام", "انجام‌شده")


@receiver(post_save, sender=Project, dispatch_uid="boards.initialize_project_board")
def initialize_project_board(sender, instance, created, **kwargs):
    if not created:
        return

    with transaction.atomic():
        board, board_created = Board.objects.get_or_create(project=instance)
        if board_created:
            BoardColumn.objects.bulk_create(
                [
                    BoardColumn(board=board, name=name, position=position)
                    for position, name in enumerate(DEFAULT_COLUMN_NAMES)
                ]
            )
