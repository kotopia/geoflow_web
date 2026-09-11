from __future__ import annotations

import argparse
import os
import stat
import tempfile
from pathlib import Path


TARGET_DATABASE = "cheonan_db"
CONFIRMATION = "ACTIVATE_QGIS_SYNC:cheonan_db:26003"
ENABLED_KEY = "GEOFLOW_GIS_PILOT_ENABLED"
DATABASES_KEY = "GEOFLOW_GIS_PILOT_DATABASES"


def _values(lines: list[str], key: str) -> list[str]:
    prefix = key + "="
    return [line.strip()[len(prefix) :].strip() for line in lines if line.strip().startswith(prefix)]


def planned_lines(lines: list[str]) -> tuple[list[str], dict[str, bool]]:
    enabled_values = _values(lines, ENABLED_KEY)
    database_values = _values(lines, DATABASES_KEY)
    if len(enabled_values) > 1 or len(database_values) > 1:
        raise RuntimeError("duplicate GIS runtime environment key")

    enabled = enabled_values[0] if enabled_values else ""
    if enabled not in {"", "0", "1"}:
        raise RuntimeError("invalid GIS pilot enabled value")

    original_allowed = {
        item.strip().lower()
        for item in (database_values[0] if database_values else "").split(",")
        if item.strip()
    }
    allowed = set(original_allowed)
    foreign = allowed - {TARGET_DATABASE}
    if enabled != "1" and foreign:
        raise RuntimeError(
            "refusing to activate an existing non-cheonan database allow-list"
        )
    allowed.add(TARGET_DATABASE)

    kept = [
        line
        for line in lines
        if not line.strip().startswith(ENABLED_KEY + "=")
        and not line.strip().startswith(DATABASES_KEY + "=")
    ]
    if kept and kept[-1] and not kept[-1].endswith("\n"):
        kept[-1] += "\n"
    kept.extend(
        [
            f"{ENABLED_KEY}=1\n",
            f"{DATABASES_KEY}={','.join(sorted(allowed))}\n",
        ]
    )
    return kept, {
        "already_enabled": enabled == "1",
        "target_already_allowed": TARGET_DATABASE in original_allowed,
    }


def apply(env_file: Path, confirmation: str) -> dict[str, bool]:
    if confirmation != CONFIRMATION:
        raise RuntimeError("activation confirmation mismatch")
    if not env_file.is_file():
        raise RuntimeError("runtime dotenv is missing")
    original = env_file.read_text(encoding="utf-8").splitlines(keepends=True)
    updated, state = planned_lines(original)
    fd, temporary = tempfile.mkstemp(
        prefix=".geoflow-qgis-sync-", dir=str(env_file.parent), text=True
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as target:
            target.writelines(updated)
            target.flush()
            os.fsync(target.fileno())
        os.chmod(temporary, stat.S_IMODE(env_file.stat().st_mode))
        os.replace(temporary, env_file)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return state


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--env-file", required=True, type=Path)
    parser.add_argument("--confirm", required=True)
    args = parser.parse_args()
    state = apply(args.env_file, args.confirm)
    print(f"qgis_sync_runtime_previously_enabled={str(state['already_enabled']).lower()}")
    print(
        "qgis_sync_runtime_target_previously_allowed="
        f"{str(state['target_already_allowed']).lower()}"
    )
    print("RESULT qgis_sync_runtime_activation=APPLIED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
