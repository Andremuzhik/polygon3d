from django.apps import AppConfig


class StudioConfig(AppConfig):
    name = "studio"
    verbose_name = "Студия"

    def ready(self):
        from . import signals  # noqa: F401
