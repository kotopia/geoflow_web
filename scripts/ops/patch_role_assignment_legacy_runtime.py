#!/usr/bin/env python3
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path


FUNCTION_START = "@require_central_admin\n@csrf_protect\ndef users_assign_group_admin(request, user_id):\n"
FUNCTION_END = "\n\n@login_required\ndef dashboard(request):"
UUID_IMPORT = "from uuid import uuid4\n"
IMPORT_ANCHOR = "from types import SimpleNamespace\n"

SAFE_MARKERS = (
    'with transaction.atomic(using="default"):',
    "FOR UPDATE OF u, g, r",
    "UPDATE user_group_map",
    "INSERT INTO user_group_map(",
    "str(uuid4())",
    "u.password_hash LIKE 'pbkdf2_sha256$%%'",
)
UNSAFE_MARKERS = (
    "ON CONFLICT (user_id, group_id)",
    "gen_random_uuid()",
)


SAFE_FUNCTION = '''@require_central_admin
@csrf_protect
def users_assign_group_admin(request, user_id):
    if request.method != "POST":
        return redirect("control:users_detail_admin", user_id=user_id)
    group_id = request.POST.get("group_id")
    role_id = request.POST.get("role_id")
    if not group_id or not role_id:
        messages.error(request, "그룹과 역할을 선택하세요.")
        return redirect("control:users_detail_admin", user_id=user_id)

    assigned = False
    with transaction.atomic(using="default"):
        with connections["default"].cursor() as cur:
            cur.execute(
                """
                SELECT u.id::text, g.id::text, r.id::text
                  FROM users u
                  JOIN groups g
                    ON g.id=%s
                   AND lower(COALESCE(g.status, ''))='active'
                  JOIN roles r ON r.id=%s
                 WHERE u.id=%s
                   AND u.is_active=TRUE
                   AND u.email_verified=TRUE
                   AND u.password_hash IS NOT NULL
                   AND length(trim(u.password_hash)) > 0
                   AND (
                       u.password_hash LIKE 'pbkdf2_sha256$%%'
                       OR u.password_hash LIKE 'bcrypt_sha256$%%'
                       OR u.password_hash LIKE '$2a$%%'
                       OR u.password_hash LIKE '$2b$%%'
                       OR u.password_hash LIKE '$2y$%%'
                   )
                 FOR UPDATE OF u, g, r
                """,
                [group_id, role_id, str(user_id)],
            )
            eligible = cur.fetchone()

            if eligible:
                eligible_user_id, eligible_group_id, eligible_role_id = eligible
                cur.execute(
                    """
                    UPDATE user_group_map
                       SET role_id=%s,
                           status='active',
                           updated_at=now()
                     WHERE user_id=%s
                       AND group_id=%s
                    RETURNING id
                    """,
                    [eligible_role_id, eligible_user_id, eligible_group_id],
                )
                assigned = cur.fetchone() is not None

                if not assigned:
                    cur.execute(
                        """
                        INSERT INTO user_group_map(
                            id, user_id, group_id, role_id,
                            status, created_at, updated_at
                        )
                        VALUES (%s, %s, %s, %s, 'active', now(), now())
                        RETURNING id
                        """,
                        [
                            str(uuid4()),
                            eligible_user_id,
                            eligible_group_id,
                            eligible_role_id,
                        ],
                    )
                    assigned = cur.fetchone() is not None

    if not assigned:
        messages.error(
            request,
            "활성화된 사용자와 유효한 그룹/역할만 지정할 수 있습니다.",
        )
        return redirect("control:users_detail_admin", user_id=user_id)

    messages.success(request, "그룹/역할이 지정되었습니다.")
    return redirect("control:users_detail_admin", user_id=user_id)
'''


def _function_bounds(source: str) -> tuple[int, int]:
    if source.count(FUNCTION_START) != 1:
        raise ValueError("role assignment function anchor is not unique")
    start = source.index(FUNCTION_START)
    end = source.find(FUNCTION_END, start)
    if end < 0:
        raise ValueError("dashboard anchor after role assignment was not found")
    return start, end


def _is_safe(function_source: str) -> bool:
    return all(marker in function_source for marker in SAFE_MARKERS) and all(
        marker not in function_source for marker in UNSAFE_MARKERS
    )


def transform_source(source: str) -> tuple[str, bool]:
    start, end = _function_bounds(source)
    current = source[start:end]
    if _is_safe(current):
        return source, False

    required_legacy_markers = (
        "INSERT INTO user_group_map(",
        "RETURNING id",
        "if not assigned:",
        "u.is_active=TRUE",
        "u.email_verified=TRUE",
        "u.password_hash IS NOT NULL",
    )
    if not all(marker in current for marker in required_legacy_markers):
        raise ValueError("role assignment source does not match a reviewed legacy shape")
    if not any(marker in current for marker in UNSAFE_MARKERS):
        raise ValueError("role assignment source is neither reviewed legacy nor safe shape")

    updated = source[:start] + SAFE_FUNCTION + source[end:]
    if UUID_IMPORT not in updated:
        if updated.count(IMPORT_ANCHOR) != 1:
            raise ValueError("uuid import anchor is not unique")
        updated = updated.replace(IMPORT_ANCHOR, IMPORT_ANCHOR + UUID_IMPORT, 1)

    new_start, new_end = _function_bounds(updated)
    if not _is_safe(updated[new_start:new_end]):
        raise ValueError("patched role assignment function failed safety contract")
    return updated, True


def patch_file(path: Path) -> bool:
    source = path.read_text(encoding="utf-8")
    updated, changed = transform_source(source)
    if not changed:
        return False

    stat = path.stat()
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(updated)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(tmp_name, stat.st_mode)
        os.replace(tmp_name, path)
    finally:
        if os.path.exists(tmp_name):
            os.unlink(tmp_name)
    return True


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: patch_role_assignment_legacy_runtime.py <views_users_admin.py>", file=sys.stderr)
        return 2
    target = Path(argv[1])
    if not target.is_file():
        print("role_assignment_runtime_patch_blocker=target_missing", file=sys.stderr)
        return 2
    try:
        changed = patch_file(target)
    except (OSError, UnicodeError, ValueError):
        print("role_assignment_runtime_patch_blocker=unexpected_source_shape", file=sys.stderr)
        return 2
    print(
        "role_assignment_runtime_patch_status="
        + ("patched" if changed else "already_safe")
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
