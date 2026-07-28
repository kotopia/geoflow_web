# Central Dashboard Log Cleanup Minimal Design

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 31d9762 phase2: analyze central dashboard log cleanup
- Analysis commit: 31d9762 phase2: analyze central dashboard log cleanup
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define a narrow cleanup for the medium-risk central dashboard diagnostic.
- Remove or sanitize the normal-path dashboard diagnostic that prints session-derived routing state.
- Preserve central dashboard rendering, permissions, routing, session behavior, and user-admin behavior.
- Avoid changing unrelated logging, routing, tests, templates, static files, settings, URLs, migrations, or DB state.

## 3. Root Cause Summary

- `control/views_users_admin.py` contains a normal-path dashboard diagnostic.
- The diagnostic logs session-derived routing state at INFO level.
- The diagnostic is not a failure, fail-closed, security, or authorization message.
- It may expose operational runtime state such as routing scope or database-routing alias context.
- No test was found that directly asserts this diagnostic.
- The issue is a medium-risk normal-path logging concern, not a behavior bug.

## 4. Future Implementation Scope

Allowed future implementation file:

- `control/views_users_admin.py`

Preferred implementation:

- Remove the identified normal-path dashboard diagnostic entirely.

Acceptable alternative only if a trace is still needed:

- Replace the diagnostic with a fixed sanitized message.
- Lower it to `logger.debug()`.
- Do not include session scope, tenant alias, connection alias, user/group identifiers, DB alias, or any runtime values.

Do not modify:

- `control/urls.py`
- `control/middleware.py`
- `control/views_auth.py`
- `control/db_router.py`
- `control/tenant_connections.py`
- `control/decorators.py`
- any tests
- any `geoflow_ops` file
- templates or static files
- `settings.py`
- `urls.py`
- migrations

## 5. Planned Cleanup

| file | diagnostic area | current issue | planned treatment |
|---|---|---|---|
| `control/views_users_admin.py` | central dashboard normal render diagnostic | INFO log includes session-derived routing state | remove preferred |
| `control/views_users_admin.py` | central dashboard trace, if still required | runtime state must not be logged | fixed sanitized DEBUG message only |

## 6. Behavior Preservation Requirements

A future implementation must not change:

- dashboard view response
- template rendering
- context data
- permission checks
- login behavior
- tenant routing
- central routing
- session reads or writes
- user-admin behavior
- URL mapping
- middleware behavior
- database queries
- database schema or data
- static files

## 7. Test Design

- No existing test directly asserts the identified dashboard diagnostic.
- No test modification is planned.
- If implementation only removes the log statement or replaces it with a fixed DEBUG message, existing behavior tests should remain unchanged.
- Do not add or modify tests unless implementation reveals a direct dependency.
- Do not weaken any login, routing, permission, or dashboard behavior coverage.

## 8. Verification Plan

After future implementation, run:

| command | expected result |
|---|---|
| `python -m py_compile control/views_users_admin.py` | passed |
| `python manage.py test control.test_group_search_login_fix` | passed |
| `python manage.py test control.test_tenant_connection_registration` | passed |
| `python manage.py check` | passed with existing W342 warning only |
| `git diff --check` | passed |
| `Test-Path geoflow_ops/templates/geoflow_ops/excel_preview.html` | False |
| `Test-Path geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` | False |

Browser smoke:

- Not required for this design task.
- After implementation, a narrow central dashboard read-only smoke may be considered only if there is uncertainty about unchanged rendering behavior.

## 9. Out of Scope

- No implementation in this design task.
- No code or test modification in this design task.
- No routing behavior change.
- No dashboard behavior change.
- No users-admin behavior change.
- No permission change.
- No template or static change.
- No settings or URL change.
- No migration.
- No DB write.
- No endpoint call.
- No browser smoke.
- No S3 or presigned URL operation.
- No Level 2 write/upload smoke.
- No W342 cleanup.
- No inactive selector cleanup.

## 10. Safety Notes

- No code was modified by this design task.
- No test was modified by this design task.
- No DB write was performed.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext or decrypted personal data was printed.
- No actual user email, group name, group UUID, tenant alias, connection alias, DB host, DB password, DB configuration value, session value, user ID, contract UUID, event UUID, attachment ID, S3 key, presigned URL, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
