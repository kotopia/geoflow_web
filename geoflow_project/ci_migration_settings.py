import os

if os.getenv("GITHUB_ACTIONS") != "true":
    raise RuntimeError("CI migration settings may only run inside GitHub Actions")

from .settings import *  # noqa: F401,F403,E402

for _config in DATABASES.values():
    _engine = str(_config.get("ENGINE") or "").lower()
    if "postgresql" in _engine or "postgis" in _engine:
        _config.setdefault("OPTIONS", {})["sslmode"] = "disable"
