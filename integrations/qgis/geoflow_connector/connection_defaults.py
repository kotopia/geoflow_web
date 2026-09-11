from __future__ import annotations


PRODUCTION_SERVER_URL = "https://geoflow.co.kr"
LEGACY_LOCAL_SERVER_URLS = frozenset(
    {
        "http://127.0.0.1:8000",
        "http://localhost:8000",
    }
)
LEGACY_DEVELOPMENT_EMAILS = frozenset({"gis-dev-admin@geoflow.invalid"})


def migrate_legacy_connection_defaults(server_url: str, email: str) -> tuple[str, str]:
    server = str(server_url or "").strip()
    normalized_server = server.rstrip("/").lower()
    if normalized_server in LEGACY_LOCAL_SERVER_URLS:
        server = PRODUCTION_SERVER_URL

    normalized_email = str(email or "").strip().lower()
    if normalized_email in LEGACY_DEVELOPMENT_EMAILS:
        normalized_email = ""
    return server, normalized_email
