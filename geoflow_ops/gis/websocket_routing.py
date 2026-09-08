from django.urls import re_path

from .websocket import ProjectGISConsumer


websocket_urlpatterns = [
    re_path(
        r"^ws/gis/projects/(?P<project_id>[0-9a-fA-F-]{36})/$",
        ProjectGISConsumer.as_asgi(),
    ),
]
