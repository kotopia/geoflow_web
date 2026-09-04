from __future__ import annotations

import http.cookiejar
import json
import re
import urllib.error
import urllib.parse
import urllib.request


_CSRF_RE = re.compile(
    r'name=["\']csrfmiddlewaretoken["\']\s+value=["\']([^"\']+)["\']',
    re.IGNORECASE,
)


class GeoFlowClientError(RuntimeError):
    pass


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class GeoFlowHttpClient:
    def __init__(self, base_url: str, timeout: int = 60):
        normalized = (base_url or "").strip().rstrip("/")
        if not normalized.startswith(("http://", "https://")):
            raise GeoFlowClientError("GeoFlow server URL must start with http:// or https://")
        self.base_url = normalized
        self.timeout = timeout
        self.cookie_jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar)
        )
        self.login_opener = urllib.request.build_opener(
            urllib.request.HTTPCookieProcessor(self.cookie_jar),
            _NoRedirect(),
        )

    def _url(self, path: str) -> str:
        if str(path).startswith(("http://", "https://")):
            return str(path)
        return urllib.parse.urljoin(self.base_url + "/", str(path).lstrip("/"))

    def _request(self, request: urllib.request.Request, *, opener=None) -> bytes:
        try:
            with (opener or self.opener).open(request, timeout=self.timeout) as response:
                return response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", errors="replace")
            raise GeoFlowClientError(
                f"GeoFlow request failed: HTTP {exc.code} {body[:300]}"
            ) from None
        except urllib.error.URLError as exc:
            raise GeoFlowClientError(f"GeoFlow connection failed: {exc.reason}") from None

    def login(self, email: str, password: str) -> list[dict]:
        email = (email or "").strip().lower()
        password = password or ""
        if not email or not password:
            raise GeoFlowClientError("Email and password are required.")

        login_url = self._url("/login/")
        login_page = self._request(
            urllib.request.Request(login_url, headers={"Accept": "text/html"})
        ).decode("utf-8", errors="replace")
        match = _CSRF_RE.search(login_page)
        if not match:
            raise GeoFlowClientError("GeoFlow login CSRF token was not found.")

        payload = urllib.parse.urlencode(
            {
                "csrfmiddlewaretoken": match.group(1),
                "email": email,
                "password": password,
            }
        ).encode("utf-8")
        request = urllib.request.Request(
            login_url,
            data=payload,
            method="POST",
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Referer": login_url,
                "Accept": "text/html,application/json",
            },
        )

        try:
            self.login_opener.open(request, timeout=self.timeout).read()
        except urllib.error.HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                body = exc.read().decode("utf-8", errors="replace")
                raise GeoFlowClientError(
                    f"GeoFlow login failed: HTTP {exc.code} {body[:300]}"
                ) from None
        except urllib.error.URLError as exc:
            raise GeoFlowClientError(f"GeoFlow login failed: {exc.reason}") from None

        response = self.get_json("/gis/api/qgis/projects/")
        results = response.get("results")
        if not isinstance(results, list):
            raise GeoFlowClientError("GeoFlow QGIS project response is invalid.")
        return results

    def get_json(self, path: str) -> dict:
        raw = self._request(
            urllib.request.Request(
                self._url(path),
                headers={"Accept": "application/json"},
            )
        )
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GeoFlowClientError("GeoFlow returned a non-JSON response.") from None
        if not isinstance(payload, dict):
            raise GeoFlowClientError("GeoFlow returned an unexpected JSON response.")
        return payload

    def get_bytes(self, path: str) -> bytes:
        return self._request(
            urllib.request.Request(
                self._url(path),
                headers={
                    "Accept": "application/geopackage+sqlite3,application/octet-stream,application/geo+json,application/json"
                },
            )
        )
