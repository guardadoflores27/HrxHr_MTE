from django.apps import AppConfig


class PlanningConfig(AppConfig):
    name = 'planning'

    def ready(self):
        # Register Time Block → Operational Event sync signals.
        from . import signals  # noqa: F401