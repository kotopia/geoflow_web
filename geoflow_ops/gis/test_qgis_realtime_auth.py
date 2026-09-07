from __future__ import annotations

from http.cookiejar import Cookie, CookieJar

from django.test import SimpleTestCase

from integrations.qgis.geoflow_connector.realtime_auth import build_realtime_cookie_header


class QgisRealtimeCookieTests(SimpleTestCase):
    @staticmethod
    def _cookie(name: str, value: str, *, domain: str, path: str = "/") -> Cookie:
        return Cookie(
            version=0,
            name=name,
            value=value,
            port=None,
            port_specified=False,
            domain=domain,
            domain_specified=True,
            domain_initial_dot=domain.startswith("."),
            path=path,
            path_specified=True,
            secure=False,
            expires=None,
            discard=True,
            comment=None,
            comment_url=None,
            rest={},
            rfc2109=False,
        )

    def test_header_keeps_only_active_host_and_path(self):
        jar = CookieJar()
        jar.set_cookie(self._cookie("sessionid", "active", domain="127.0.0.1"))
        jar.set_cookie(self._cookie("csrftoken", "csrf", domain="127.0.0.1"))
        jar.set_cookie(self._cookie("sessionid", "other-host", domain="localhost"))
        jar.set_cookie(self._cookie("login_only", "x", domain="127.0.0.1", path="/login/"))

        header = build_realtime_cookie_header(
            jar,
            "http://127.0.0.1:8000",
            "/ws/gis/projects/11111111-1111-4111-8111-111111111401/",
        )

        self.assertIn("sessionid=active", header)
        self.assertIn("csrftoken=csrf", header)
        self.assertNotIn("other-host", header)
        self.assertNotIn("login_only", header)

    def test_header_deduplicates_cookie_names(self):
        jar = [
            self._cookie("sessionid", "broad", domain=".example.com"),
            self._cookie("sessionid", "exact", domain="gis.example.com"),
        ]
        header = build_realtime_cookie_header(
            jar,
            "https://gis.example.com",
            "/ws/gis/projects/x/",
        )
        self.assertEqual(header, "sessionid=exact")
