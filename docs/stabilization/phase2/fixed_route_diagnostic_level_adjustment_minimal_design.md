# Fixed Route Diagnostic Level Adjustment Minimal Design

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: f3f0306 phase2: analyze fixed route diagnostic levels
- Analysis commit: f3f0306 phase2: analyze fixed route diagnostic levels
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define a narrow future change that lowers routine, successful routing diagnostics from `INFO` to `DEBUG`.
- Keep failure, availability, and authorization diagnostics at `WARNING` or their existing higher severity.
- Preserve all current routing, session, tenant-connection, and fail-closed behavior.
- Limit any test change to the log level expected by assertions that directly capture the affected routine messages.

## 3. Design Principle

This design changes log severity only. A future implementation must not change:

- routing conditions or redirect targets
- session keys or session mutation
- tenant candidate filtering or selection validation
- database connection registration or verification
- middleware order
- settings, URLs, templates, or static assets
- migrations, database schema, or database data

All diagnostic messages must remain sanitized. Normal successful route decisions may move to `DEBUG`, while operational failure and security-relevant warnings must remain visible at their current warning level.

## 4. Future Implementation Scope

Allowed files for a future implementation:

- `control/middleware.py`
- `control/views_auth.py`
- `control/test_tenant_connection_registration.py`

The test file may be changed only if it directly asserts an affected `INFO` log. Such a change must update only the captured log level or corresponding fixed-message expectation while retaining the existing routing and fail-closed assertions.

Do not modify:

- `control/db_router.py`
- `control/tenant_connections.py`
- `control/decorators.py`
- `control/views_users_admin.py`
- any `geoflow_ops` file
- templates or static files
- `settings.py`
- `urls.py`
- migrations

## 5. Planned Log-Level Changes

Routine successful diagnostics proposed for adjustment:

| location | diagnostic category | current level | planned level |
|---|---|---:|---:|
| `control/middleware.py` | normal central route resolution | INFO | DEBUG |
| `control/middleware.py` | normal tenant route resolution | INFO | DEBUG |
| `control/middleware.py` | expected central-route guard decision | INFO | DEBUG |
| `control/views_auth.py` | expected tenant-candidate or central-route decision | INFO | DEBUG |
| `control/views_auth.py` | successful post-login route decision | INFO | DEBUG |

Diagnostics that must retain their current severity:

| location | diagnostic category | required treatment |
|---|---|---|
| `control/middleware.py` | tenant connection unavailable | keep WARNING |
| `control/db_router.py` | normal routing detail | keep DEBUG |
| `control/db_router.py` | unavailable or unregistered route target | keep WARNING |
| `control/tenant_connections.py` | connection verification or configuration failure | keep WARNING |
| `control/views_auth.py` | authentication or candidate lookup failure | keep WARNING or existing exception severity |
| `control/views_auth.py` | post-login tenant connection unavailable | keep WARNING |
| `control/decorators.py` | authorization denial | keep WARNING |

Only fixed, sanitized messages are permitted. No runtime alias, identifier, database configuration value, user information, or session contents may be added.

## 6. Test Update

Existing behavior assertions must continue to verify:

- middleware routing behavior
- tenant connection preparation behavior
- central fallback behavior
- session cleanup on failure
- fail-closed handling
- HTTP status and redirect behavior where currently covered

If an existing test captures a routine middleware message at `INFO`, it may be updated to capture that same fixed message at `DEBUG`. Tests must not be deleted or weakened.

Allowed test adjustments are limited to:

- changing `assertLogs` or equivalent capture level from `INFO` to `DEBUG`
- updating a fixed log-level prefix when the assertion includes the severity

The following must not change:

- test setup semantics
- routing inputs or expectations
- session-state expectations
- status-code expectations
- fail-closed assertions

Warning diagnostics must remain asserted at `WARNING` where they are currently covered. Test data and assertion output must not contain actual aliases, UUIDs, group identifiers, user identifiers, database configuration, or other runtime identifiers.

## 7. Deferred

The following remain deferred:

- central dashboard diagnostic cleanup of medium-risk paths
- inactive selector diagnostic removal
- unrelated test-only cleanup
- `catalog.CategoryParent.child` W342 warning cleanup
- Level 2 controlled write/upload smoke
- tenant metadata repair for non-selectable groups
- broad AdminKit-derived template cleanup

## 8. Verification

After a future implementation, run:

| command | expected result |
|---|---|
| `python -m py_compile control/middleware.py control/views_auth.py` | passed |
| `python manage.py test control.test_group_search_login_fix` | passed |
| `python manage.py test control.test_tenant_connection_registration` | passed |
| `python manage.py check` | passed with the existing W342 warning only |
| `git diff --check` | passed |
| `Test-Path geoflow_ops/templates/geoflow_ops/excel_preview.html` | False |
| `Test-Path geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` | False |

A browser smoke is not required for this design task. After the future log-only implementation, a read-only smoke may be considered only if validation leaves uncertainty about unchanged runtime behavior.

## 9. Out of Scope

- No implementation in this design task
- No routing, redirect, session, candidate, middleware, router, or tenant-connection behavior change
- No authorization or permission change
- No application endpoint behavior change
- No test modification in this design task
- No settings, URL, template, static, migration, schema, or data change
- No browser smoke
- No database or S3 operation

## 10. Safety Notes

- No code or test was modified by this design task.
- No DB write was performed.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext or decrypted personal data was printed.
- No actual user email, group name, group UUID, tenant alias, connection alias, DB host, DB password, DB configuration value, contract UUID, event UUID, attachment ID, S3 key, presigned URL, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
