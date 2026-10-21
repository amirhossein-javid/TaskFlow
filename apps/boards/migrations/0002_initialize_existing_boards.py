from django.db import migrations

DEFAULT_COLUMN_NAMES = ("برای انجام", "در حال انجام", "انجام‌شده")


def initialize_existing_boards(apps, schema_editor):
    Project = apps.get_model("projects", "Project")
    Board = apps.get_model("boards", "Board")
    BoardColumn = apps.get_model("boards", "BoardColumn")

    for project_id in Project.objects.values_list("id", flat=True).iterator():
        board, _ = Board.objects.get_or_create(project_id=project_id)
        if not BoardColumn.objects.filter(board=board).exists():
            BoardColumn.objects.bulk_create(
                [
                    BoardColumn(board=board, name=name, position=position)
                    for position, name in enumerate(DEFAULT_COLUMN_NAMES)
                ]
            )


def remove_initialized_boards(apps, schema_editor):
    Board = apps.get_model("boards", "Board")
    Board.objects.all().delete()


class Migration(migrations.Migration):
    dependencies = [("boards", "0001_initial")]

    operations = [
        migrations.RunPython(initialize_existing_boards, remove_initialized_boards),
    ]
