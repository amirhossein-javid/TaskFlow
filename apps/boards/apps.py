from django.apps import AppConfig


class BoardsConfig(AppConfig):
    default_auto_field = "django.db.models.BigAutoField"
    name = "apps.boards"
    verbose_name = "بردها"

    def ready(self):
        from . import signals  # noqa: F401
