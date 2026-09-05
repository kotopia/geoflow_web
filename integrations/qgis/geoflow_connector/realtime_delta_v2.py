from __future__ import annotations

from qgis.core import Qgis

from .realtime_auth import build_realtime_cookie_header
from .realtime_delta import RealtimeDeltaMixin


class RealtimeDeltaV2Mixin(RealtimeDeltaMixin):
    """Harden QGIS realtime auth and remove aggressive fallback polling.

    - Send only host/path-matching cookies to QWebSocket.
    - Poll Delta every 15 seconds only while WebSocket is unavailable.
    - Back off rejected/disconnected WebSocket reconnects instead of retrying
      every few seconds indefinitely.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._realtime_poll_timer.setInterval(15_000)
        self._realtime_reconnect_timer.setInterval(15_000)

    @staticmethod
    def _cookie_header(client) -> str:
        return build_realtime_cookie_header(
            getattr(client, "cookie_jar", ()),
            getattr(client, "base_url", ""),
            "/ws/gis/",
        )

    def _on_realtime_connected(self, socket) -> None:
        self._realtime_reconnect_timer.setInterval(15_000)
        super()._on_realtime_connected(socket)

    def _on_realtime_disconnected(self, socket) -> None:
        if socket is not self._realtime_socket:
            return

        close_code = 0
        try:
            close_code = int(socket.closeCode())
        except Exception:
            close_code = 0

        self._realtime_socket = None
        self._realtime_socket_connected = False
        try:
            socket.deleteLater()
        except Exception:
            pass

        if not self._realtime_transport_available():
            return

        # Keep multi-user refresh available, but make the fallback cheap.  An
        # authorization rejection should not generate a reconnect storm.
        self._start_poll_fallback(announce=False)
        if close_code in (4400, 4401, 4403):
            self._realtime_reconnect_timer.setInterval(60_000)
            if not self._realtime_fallback_announced:
                self._realtime_fallback_announced = True
                self.iface.messageBar().pushMessage(
                    "GeoFlow",
                    "QGIS WebSocket 인증이 거부되어 저빈도 Delta 폴링으로 전환했습니다.",
                    level=Qgis.Warning,
                    duration=6,
                )
        else:
            self._realtime_reconnect_timer.setInterval(15_000)
        self._realtime_reconnect_timer.start()

    def _run_realtime_poll(self) -> None:
        if not self._realtime_transport_available():
            return
        if self._realtime_socket_connected:
            return

        self._realtime_force_pull = True
        self._run_realtime_delta_pull()
        if self._realtime_transport_available() and not self._realtime_socket_connected:
            self._realtime_poll_timer.start(15_000)
