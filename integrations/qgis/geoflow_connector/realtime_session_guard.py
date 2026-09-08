from __future__ import annotations

import urllib.error
import urllib.parse
import urllib.request

from qgis.core import Qgis


_REDIRECT_CODES = {301, 302, 303, 307, 308}


class RealtimeSessionGuardMixin:
    """Stop fallback/reconnect traffic when the authenticated QGIS session expires.

    The isolated GeoFlow dev launcher intentionally rotates DJANGO_SECRET_KEY on
    each restart, so cookies from a previously running development server become
    unreadable.  Without this guard an already-open QGIS client can keep polling
    Delta and retrying WebSocket authentication until the user logs in again.

    We probe the authenticated projects endpoint only after a realtime socket
    disconnect/rejection.  A redirect to /login/ or HTTP 401 is authoritative
    session loss; network/server failures remain ordinary fallback conditions.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._realtime_session_probe_required = False
        self._realtime_session_expiry_announced = False

    def _materialize_project(self, manifest: dict, client) -> dict:
        self._realtime_session_probe_required = False
        self._realtime_session_expiry_announced = False
        return super()._materialize_project(manifest, client)

    def _on_realtime_connected(self, socket) -> None:
        self._realtime_session_probe_required = False
        self._realtime_session_expiry_announced = False
        return super()._on_realtime_connected(socket)

    def _on_realtime_disconnected(self, socket) -> None:
        if socket is getattr(self, "_realtime_socket", None):
            self._realtime_session_probe_required = True
        return super()._on_realtime_disconnected(socket)

    def _session_state_after_disconnect(self):
        """Return True/False for known auth state, or None for indeterminate I/O."""

        client = getattr(self, "active_client", None)
        if client is None:
            return None
        opener = getattr(client, "login_opener", None)
        url_builder = getattr(client, "_url", None)
        if opener is None or not callable(url_builder):
            return None

        request = urllib.request.Request(
            url_builder("/gis/api/qgis/projects/"),
            headers={"Accept": "application/json"},
        )
        try:
            with opener.open(request, timeout=min(int(getattr(client, "timeout", 30)), 10)) as response:
                status = int(getattr(response, "status", 200) or 200)
                final_url = str(getattr(response, "geturl", lambda: "")() or "")
                if urllib.parse.urlsplit(final_url).path.startswith("/login/"):
                    return False
                return True if status == 200 else None
        except urllib.error.HTTPError as exc:
            if exc.code == 401:
                return False
            if exc.code in _REDIRECT_CODES:
                location = str(exc.headers.get("Location") or "")
                path = urllib.parse.urlsplit(
                    urllib.parse.urljoin(request.full_url, location)
                ).path
                if path.startswith("/login/"):
                    return False
            return None
        except urllib.error.URLError:
            return None
        except Exception:
            return None

    def _halt_realtime_for_expired_session(self) -> None:
        self._realtime_session_probe_required = False
        for timer_name in (
            "_realtime_delta_timer",
            "_realtime_reconnect_timer",
            "_realtime_poll_timer",
        ):
            timer = getattr(self, timer_name, None)
            if timer is not None:
                try:
                    timer.stop()
                except Exception:
                    pass
        try:
            self._stop_realtime_socket()
        except Exception:
            pass
        if not self._realtime_session_expiry_announced:
            self._realtime_session_expiry_announced = True
            self.iface.messageBar().pushMessage(
                "GeoFlow",
                "GeoFlow 로그인 세션이 만료되었습니다. Connector에서 다시 로그인하면 실시간 동기화가 재개됩니다.",
                level=Qgis.Warning,
                duration=10,
            )

    def _guard_realtime_session(self) -> bool:
        if not self._realtime_session_probe_required:
            return True
        state = self._session_state_after_disconnect()
        if state is False:
            self._halt_realtime_for_expired_session()
            return False
        if state is True:
            self._realtime_session_probe_required = False
        return True

    def _run_realtime_poll(self) -> None:
        if not self._guard_realtime_session():
            return
        return super()._run_realtime_poll()

    def _start_realtime_socket(self) -> None:
        if not self._guard_realtime_session():
            return
        return super()._start_realtime_socket()
