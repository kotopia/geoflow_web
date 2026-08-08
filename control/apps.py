import os

from django.apps import AppConfig
from django.conf import settings


def _apply_runtime_environment_overrides() -> None:
    default_from_email = (os.environ.get("DEFAULT_FROM_EMAIL") or "").strip()
    if default_from_email:
        settings.DEFAULT_FROM_EMAIL = default_from_email

    site_origin = (os.environ.get("SITE_ORIGIN") or "").strip()
    if site_origin:
        settings.SITE_ORIGIN = site_origin.rstrip("/")


class ControlConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'control'

    def ready(self):
        _apply_runtime_environment_overrides()
