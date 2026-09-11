"""Render units using validated paths from the running GeoFlow service."""
import re
import sys
from pathlib import Path


def render(repo, python, user, group):
    for value in (repo, python):
        if not value.startswith("/") or not re.fullmatch(r"[A-Za-z0-9_./-]+", value):
            raise ValueError("Unsupported service path")
    for value in (user, group):
        if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]*", value) or value == "root":
            raise ValueError("Explicit non-root service identity required")
    service = f"""[Unit]
Description=GeoFlow central bid collector
After=network-online.target

[Service]
Type=oneshot
User={user}
Group={group}
WorkingDirectory={repo}
ExecStart={python} {repo}/manage.py collect_central_bids --request-budget 100 --max-steps 10
Environment=PYTHONUNBUFFERED=1
TimeoutStartSec=900
Nice=10
NoNewPrivileges=true
PrivateTmp=true
"""
    timer = """[Unit]
Description=Process central bid queue; incremental refresh once per hour

[Timer]
OnBootSec=2min
OnUnitInactiveSec=5min
Unit=geoflow-bid-collector.service

[Install]
WantedBy=timers.target
"""
    return service, timer


if __name__ == "__main__":
    repo, python, user, group, destination = sys.argv[1:]
    for name, content in zip(("geoflow-bid-collector.service", "geoflow-bid-collector.timer"),
                             render(repo, python, user, group)):
        (Path(destination) / name).write_text(content)
