from __future__ import annotations

import sqlite3


def stamp_project_cache_state(package_path: str, manifest: dict) -> None:
    project = manifest.get("project") or {}
    status = str(project.get("status") or "")
    code = str(project.get("code") or "")
    conn = sqlite3.connect(package_path, timeout=30)
    try:
        conn.execute("PRAGMA busy_timeout=30000")
        conn.executemany(
            "INSERT OR REPLACE INTO _geoflow_package(key,value) VALUES (?,?)",
            [
                ("cache_project_status", status),
                ("cache_project_code", code),
            ],
        )
        conn.commit()
    finally:
        conn.close()
