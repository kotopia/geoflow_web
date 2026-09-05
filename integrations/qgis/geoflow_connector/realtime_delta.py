from __future__ import annotations

import json
import urllib.parse

from qgis.PyQt.QtCore import QByteArray, QTimer, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest
from qgis.core import Qgis

try:
    from qgis.PyQt.QtWebSockets import QWebSocket
except ImportError:  # pragma: no cover - depends on the bundled QGIS Qt build
    QWebSocket = None

from .changeset_queue import read_last_applied_revision


class RealtimeDeltaMixin:
    """Use GeoFlow WebSocket events as hints to pull revision Delta into QGIS.

    The socket never carries feature payloads and never writes directly to the
    database.  It only tells QGIS that a project revision changed.  QGIS then
    uses the existing authenticated Delta API, so reconnects and missed socket
    messages remain recoverable from ``last_applied_revision``.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._realtime_socket = None
        self._realtime_pending_revision = 0
        self._realtime_force_pull = False
        self._realtime_delta_retry_count = 0

        self._realtime_delta_timer = QTimer()
        self._realtime_delta_timer.setSingleShot(True)
        self._realtime_delta_timer.setInterval(350)
        self._realtime_delta_timer.timeout.connect(self._run_realtime_delta_pull)

        self._realtime_reconnect_timer = QTimer()
        self._realtime_reconnect_timer.setSingleShot(True)
        self._realtime_reconnect_timer.setInterval(2500)
        self._realtime_reconnect_timer.timeout.connect(self._start_realtime_socket)

    def unload(self):
        self._realtime_delta_timer.stop()
        self._realtime_reconnect_timer.stop()
        self._stop_realtime_socket()
        super().unload()

    def _materialize_project(self, manifest: dict, client) -> dict:
        self._realtime_delta_timer.stop()
        self._realtime_reconnect_timer.stop()
        self._stop_realtime_socket()
        self._realtime_pending_revision = 0
        self._realtime_force_pull = False
        self._realtime_delta_retry_count = 0

        result = super()._materialize_project(manifest, client)
        self._start_realtime_socket()
        return result

    def _realtime_transport(self) -> dict:
        return ((self.active_context or {}).get("manifest") or {}).get("transport") or {}

    def _realtime_available(self) -> bool:
        transport = self._realtime_transport()
        return bool(
            QWebSocket is not None
            and self.active_client is not None
            and (self.active_context or {}).get("changeset_supported")
            and transport.get("realtime_supported")
            and transport.get("realtime_url")
            and transport.get("delta_url")
        )

    @staticmethod
    def _cookie_header(client) -> str:
        parts = []
        for cookie in getattr(client, "cookie_jar", ()):
            name = str(getattr(cookie, "name", "") or "")
            value = str(getattr(cookie, "value", "") or "")
            if name and value:
                parts.append(f"{name}={value}")
        return "; ".join(parts)

    @staticmethod
    def _websocket_url(base_url: str, path: str) -> str:
        absolute_http = urllib.parse.urljoin(
            str(base_url).rstrip("/") + "/",
            str(path).lstrip("/"),
        )
        parsed = urllib.parse.urlsplit(absolute_http)
        if parsed.scheme == "https":
            scheme = "wss"
        elif parsed.scheme == "http":
            scheme = "ws"
        else:
            raise RuntimeError("GeoFlow realtime URL requires an http/https server URL.")
        return urllib.parse.urlunsplit(
            (scheme, parsed.netloc, parsed.path, parsed.query, parsed.fragment)
        )

    def _stop_realtime_socket(self) -> None:
        socket = self._realtime_socket
        self._realtime_socket = None
        if socket is None:
            return
        try:
            socket.abort()
        except Exception:
            try:
                socket.close()
            except Exception:
                pass
        try:
            socket.deleteLater()
        except Exception:
            pass

    def _start_realtime_socket(self) -> None:
        self._realtime_reconnect_timer.stop()
        if not self._realtime_available():
            return

        self._stop_realtime_socket()
        client = self.active_client
        transport = self._realtime_transport()
        try:
            ws_url = self._websocket_url(client.base_url, transport.get("realtime_url"))
            cookie_header = self._cookie_header(client)
            if not cookie_header:
                raise RuntimeError("GeoFlow realtime session cookie is unavailable.")

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
                QByteArray(b"Cookie"),
                QByteArray(cookie_header.encode("utf-8")),
            )
            socket.open(request)
        except Exception as exc:
            self._stop_realtime_socket()
            self.iface.messageBar().pushMessage(
                "GeoFlow QGIS 실시간 연결 실패",
                str(exc),
                level=Qgis.Warning,
                duration=6,
            )
            self._realtime_reconnect_timer.start()

    def _on_realtime_connected(self, socket) -> None:
        if socket is not self._realtime_socket:
            return
        self.iface.messageBar().pushMessage(
            "GeoFlow",
            "QGIS 실시간 Delta 연결됨",
            level=Qgis.Success,
            duration=4,
        )

    def _on_realtime_disconnected(self, socket) -> None:
        if socket is not self._realtime_socket:
            return
        self._realtime_socket = None
        try:
            socket.deleteLater()
        except Exception:
            pass
        if self._realtime_available():
            self._realtime_reconnect_timer.start()

    def _on_realtime_message(self, socket, text: str) -> None:
        if socket is not self._realtime_socket:
            return
        try:
            payload = json.loads(str(text))
        except (TypeError, ValueError, json.JSONDecodeError):
            return
        if not isinstance(payload, dict):
            return

        project_id = str((self.active_context or {}).get("project_id") or "")
        if str(payload.get("project_id") or "") != project_id:
            return

        event_type = str(payload.get("type") or "")
        if event_type == "gis.realtime.ready":
            # A reconnect may have missed any number of notifications.  One
            # cursor-based Delta pull closes that gap without a new Snapshot.
            self._realtime_force_pull = True
            self._realtime_delta_timer.start()
            return
        if event_type != "gis.project.change":
            return

        try:
            revision = int(payload.get("current_revision") or 0)
        except (TypeError, ValueError):
            revision = 0
        if revision <= 0:
            return

        package_path = str((self.active_context or {}).get("package_path") or "")
        if package_path:
            try:
                if revision <= read_last_applied_revision(package_path):
                    return
            except Exception:
                pass

        self._realtime_pending_revision = max(
            self._realtime_pending_revision,
            revision,
        )
        self._realtime_delta_retry_count = 0
        # Coalesce a burst (for example hundreds of object revisions in one
        # Changeset) into a single Delta request.
        self._realtime_delta_timer.start()

    def _managed_layer_has_unsaved_edits(self) -> bool:
        for layer in self._managed_layers():
            try:
                if layer.isModified():
                    return True
            except Exception:
                continue
        return False

    def _run_realtime_delta_pull(self) -> None:
        if not self._realtime_available():
            return
        if self._sync_in_progress or self._managed_layer_has_unsaved_edits():
            self._realtime_delta_timer.start(800)
            return

        package_path = str((self.active_context or {}).get("package_path") or "")
        if not package_path:
            return
        try:
            cursor = read_last_applied_revision(package_path)
        except Exception:
            cursor = 0

        if (
            not self._realtime_force_pull
            and self._realtime_pending_revision
            and cursor >= self._realtime_pending_revision
        ):
            self._realtime_pending_revision = 0
            return

        self._sync_in_progress = True
        try:
            received = int(self._pull_and_apply_delta(self.active_client) or 0)
            self._realtime_force_pull = False
            self._realtime_delta_retry_count = 0
            new_cursor = read_last_applied_revision(package_path)
            if new_cursor >= self._realtime_pending_revision:
                self._realtime_pending_revision = 0
            if received:
                self.iface.messageBar().pushMessage(
                    "GeoFlow",
                    f"다른 작업자의 GIS 변경 {received}건 실시간 수신",
                    level=Qgis.Success,
                    duration=5,
                )
        except Exception as exc:
            self._realtime_delta_retry_count += 1
            if self._realtime_delta_retry_count <= 3:
                self._realtime_delta_timer.start(2000 * self._realtime_delta_retry_count)
            else:
                self._realtime_delta_retry_count = 0
                self.iface.messageBar().pushMessage(
                    "GeoFlow 실시간 Delta 수신 실패",
                    str(exc),
                    level=Qgis.Warning,
                    duration=8,
                )
        finally:
            self._sync_in_progress = False
