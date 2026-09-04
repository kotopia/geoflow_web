from __future__ import annotations

import http.cookiejar
import json
import mimetypes
import os
import re
import sqlite3
import tempfile
import urllib.error
import urllib.parse
import urllib.request
import uuid


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
    def __init__(self, base_url: str, timeout: int = 30):
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

    def _cookie_value(self, name: str) -> str:
        for cookie in self.cookie_jar:
            if cookie.name == name:
                return cookie.value or ""
        return ""

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
                    "Accept": "application/geopackage+sqlite3,application/geo+json,application/json"
                },
            )
        )

    @staticmethod
    def _checkpoint_sqlite_bytes(file_path: str) -> bytes:
        """Return one consistent SQLite image including committed WAL contents."""
        temp = tempfile.NamedTemporaryFile(
            prefix="geoflow-qgis-sync-",
            suffix=".gpkg",
            delete=False,
        )
        temp_path = temp.name
        temp.close()
        source = None
        target = None
        try:
            source = sqlite3.connect(file_path, timeout=30)
            target = sqlite3.connect(temp_path, timeout=30)
            source.backup(target)
            target.commit()
            target.close()
            target = None
            source.close()
            source = None
            with open(temp_path, "rb") as handle:
                return handle.read()
        except sqlite3.Error as exc:
            raise GeoFlowClientError(
                f"GeoPackage 저장 상태를 확정할 수 없습니다: {exc}"
            ) from None
        finally:
            if target is not None:
                target.close()
            if source is not None:
                source.close()
            try:
                os.remove(temp_path)
            except OSError:
                pass

    def post_file_json(self, path: str, file_path: str, *, field_name: str = "package") -> dict:
        csrf = self._cookie_value("csrftoken")
        if not csrf:
            raise GeoFlowClientError("GeoFlow CSRF cookie is unavailable. Log in again.")
        if not os.path.isfile(file_path):
            raise GeoFlowClientError("GeoPackage file does not exist.")

        boundary = "----GeoFlowSync" + uuid.uuid4().hex
        file_name = os.path.basename(file_path)
        content_type = mimetypes.guess_type(file_name)[0] or "application/geopackage+sqlite3"
        file_bytes = self._checkpoint_sqlite_bytes(file_path)

        body = b"".join(
            [
                f"--{boundary}\r\n".encode("ascii"),
                (
                    f'Content-Disposition: form-data; name="{field_name}"; filename="{file_name}"\r\n'
                ).encode("utf-8"),
                f"Content-Type: {content_type}\r\n\r\n".encode("ascii"),
                file_bytes,
                b"\r\n",
                f"--{boundary}--\r\n".encode("ascii"),
            ]
        )

        request = urllib.request.Request(
            self._url(path),
            data=body,
            method="POST",
            headers={
                "Content-Type": f"multipart/form-data; boundary={boundary}",
                "Content-Length": str(len(body)),
                "Accept": "application/json",
                "X-CSRFToken": csrf,
                "Referer": self._url("/gis/"),
            },
        )
        try:
            with self.opener.open(request, timeout=max(self.timeout, 120)) as response:
                raw = response.read()
        except urllib.error.HTTPError as exc:
            raw = exc.read()
            try:
                payload = json.loads(raw.decode("utf-8"))
                message = payload.get("message") or payload.get("error") or f"HTTP {exc.code}"
                conflicts = payload.get("conflicts") or []
                if conflicts:
                    message += f" (충돌 {len(conflicts)}건)"
            except Exception:
                message = raw.decode("utf-8", errors="replace")[:300]
            raise GeoFlowClientError(f"GeoFlow sync failed: {message}") from None
        except urllib.error.URLError as exc:
            raise GeoFlowClientError(f"GeoFlow sync connection failed: {exc.reason}") from None

        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise GeoFlowClientError("GeoFlow sync returned a non-JSON response.") from None
        if not isinstance(payload, dict) or not payload.get("ok"):
            raise GeoFlowClientError("GeoFlow sync returned an invalid response.")
        return payload
