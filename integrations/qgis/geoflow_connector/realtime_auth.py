from __future__ import annotations

import urllib.parse


def build_realtime_cookie_header(cookie_jar, base_url: str, target_path: str = "/ws/") -> str:
    """Build one deterministic Cookie header for the GeoFlow WebSocket host.

    ``http.cookiejar.CookieJar`` can contain cookies for more than one host/path
    after repeated local logins.  Dumping the entire jar into a WebSocket
    request can therefore send duplicate ``sessionid`` values.  HTTP requests
    do not have this problem because CookieJar selects matching cookies for the
    target URL.  Apply the same host/path filtering here before handing the
    header to QWebSocket.
    """

    parsed = urllib.parse.urlsplit(str(base_url or ""))
    host = str(parsed.hostname or "").lower()
    scheme = str(parsed.scheme or "").lower()
    path = str(target_path or "/")
    if not host:
        return ""

    selected: dict[str, tuple[tuple[int, int], str]] = {}
    for cookie in cookie_jar or ():
        name = str(getattr(cookie, "name", "") or "")
        value = str(getattr(cookie, "value", "") or "")
        if not name or not value:
            continue

        domain = str(getattr(cookie, "domain", "") or "").lstrip(".").lower()
        if domain and host != domain and not host.endswith("." + domain):
            continue

        cookie_path = str(getattr(cookie, "path", "") or "/")
        if not path.startswith(cookie_path.rstrip("/") + "/") and path != cookie_path:
            if cookie_path != "/":
                continue

        if bool(getattr(cookie, "secure", False)) and scheme != "https":
            continue

        rank = (1 if domain == host else 0, len(cookie_path))
        previous = selected.get(name)
        if previous is None or rank >= previous[0]:
            selected[name] = (rank, value)

    return "; ".join(
        f"{name}={selected[name][1]}"
        for name in sorted(selected)
    )
