"""ASGI entrypoint for GeoFlow HTTP and development GIS WebSocket traffic."""

import os

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "geoflow_project.settings")

from django.conf import settings  # noqa: E402
from django.core.asgi import get_asgi_application  # noqa: E402


django_application = get_asgi_application()
_strict_gis_dev = bool(
    settings.DEBUG and os.getenv("GEOFLOW_DEV_RUNTIME_STRICT") == "1"
)

if _strict_gis_dev:
    # One-process in-memory delivery is intentionally limited to the isolated
    # development runtime. Production rollout requires a separately reviewed
    # Redis-backed channel layer and ASGI deployment.
    settings.CHANNEL_LAYERS = {
        "default": {
            "BACKEND": "channels.layers.InMemoryChannelLayer",
        }
    }

    from channels.auth import AuthMiddlewareStack  # noqa: E402
    from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
    from django.contrib.staticfiles.handlers import ASGIStaticFilesHandler  # noqa: E402

    from geoflow_ops.gis.websocket_routing import websocket_urlpatterns  # noqa: E402
    from geoflow_ops.gis.websocket_security import (  # noqa: E402
        TicketAwareAllowedHostsOriginValidator,
    )

    websocket_application = AuthMiddlewareStack(URLRouter(websocket_urlpatterns))
    application = ProtocolTypeRouter(
        {
            "http": ASGIStaticFilesHandler(django_application),
            "websocket": TicketAwareAllowedHostsOriginValidator(
                websocket_application
            ),
        }
    )
else:
    application = django_application
