from django.apps import AppConfig


class GeoflowOpsConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'geoflow_ops'
    label = 'webgisapp'
    verbose_name = 'GeoFlow Operations'

    def ready(self):
        # Import signal registrations once the app registry is ready.
        from . import signals  # noqa: F401
