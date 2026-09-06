from __future__ import annotations

from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import Qgis

from .realtime_delta import QWebSocket
from .realtime_delta_v2 import RealtimeDeltaV2Mixin


class RealtimeDeltaV3Mixin(RealtimeDeltaV2Mixin):
    """Authenticate QGIS WebSocket with a short-lived server-signed ticket.

    QGIS' urllib HTTP client and Qt WebSocket client use different cookie
    implementations.  Relying on a copied Django session cookie proved brittle
    on QGIS 4/Qt6.  Obtain the ticket over the already-authenticated HTTP
    session, then present it as a bearer header during the WebSocket handshake.
    """

    def _realtime_ticket_path(self) -> str:
        project_id = str((self.active_context or {}).get("project_id") or "")
        return f"/gis/projects/{project_id}/api/qgis-realtime-ticket/"

    def _start_realtime_socket(self) -> None:
        self._realtime_reconnect_timer.stop()
        if not self._realtime_transport_available():
            return

        if not self._realtime_websocket_available():
            self._start_poll_fallback(announce=True)
            return

        self._stop_realtime_socket()
        client = self.active_client
        transport = self._realtime_transport()
        try:
            ticket_payload = client.get_json(self._realtime_ticket_path())
            ticket = str(ticket_payload.get("token") or "")
            if not ticket_payload.get("ok") or not ticket:
                raise RuntimeError("GeoFlow realtime ticket was not issued.")

            ws_url = self._websocket_url(client.base_url, transport.get("realtime_url"))
            socket = QWebSocket()
            self._realtime_socket = socket
            if hasattr(socket, "setOrigin"):
                socket.setOrigin(str(client.base_url))

            socket.connected.connect(
                lambda sock=socket: self._on_realtime_connected(sock)
            )
            socket.disconnected.connect(
                lambda sock=socket: self._on_realtime_disconnected(sock)
            )
            socket.textMessageReceived.connect(
                lambda text, sock=socket: self._on_realtime_message(sock, text)
            )

            request = QNetworkRequest(QUrl(ws_url))
            request.setRawHeader(
                QByteArray(b"Authorization"),
                QByteArray(("Bearer " + ticket).encode("utf-8")),
            )
            socket.open(request)
            # A failed/unsupported handshake still falls back to a low-rate
            # Delta poll while the reconnect path obtains a fresh ticket.
            self._realtime_poll_timer.start(3_000)
        except Exception as exc:
            self._stop_realtime_socket()
            self.iface.messageBar().pushMessage(
                "GeoFlow QGIS 실시간 연결 실패",
                str(exc),
                level=Qgis.Warning,
                duration=6,
            )
            self._start_poll_fallback(announce=True)
            self._realtime_reconnect_timer.setInterval(60_000)
            self._realtime_reconnect_timer.start()
