# Test-only Diagnostic Cleanup Minimal Design

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 3a03802 phase2: analyze test-only diagnostic cleanup
- Analysis commit: 3a03802 phase2: analyze test-only diagnostic cleanup
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define a narrow cleanup for one stale test-only diagnostic patch.
- Remove a logger-method patch that no longer intercepts the active production logging call.
- Preserve all test behavior assertions.
- Avoid modifying production code, routing behavior, session behavior, tenant connection behavior, settings, templates, static files, migrations, or DB state.

## 3. Analysis Summary

- No standalone test `print()` call was found.
- No `assertLogs` usage was found.
- Most logger mocks are intentional and should remain.
- Sanitized log non-disclosure assertions should remain.
- Fail-closed, CSRF, and expected warning suppression should remain.
- One stale logger-method patch was identified in `control/test_group_search_login_fix.py`.
- The stale patch targets a superseded logger method that production code no longer calls after normal-route diagnostics were lowered to DEBUG.
- Production impact is none.

## 4. Future Implementation Scope

Allowed future implementation file:

- `control/test_group_search_login_fix.py`

Planned implementation:

- Remove only the stale logger-method patch from the shared login-test patch tuple.

Do not modify:

- production code
- `control/test_tenant_connection_registration.py`
- `geoflow_ops` tests
- remaining mocks
- test inputs
- test candidate data
- routing assertions
- redirect assertions
- session assertions
- status-code assertions
- fail-closed assertions
- CSRF assertions
- settings, templates, static files, migrations, or database state

## 5. Cleanup Rule

A future implementation must:

- Remove only the stale patch if it is still unused.
- Stop and defer if the patch is found to still intercept an active call.
- Avoid weakening any regression assertion.
- Avoid changing test setup semantics.
- Avoid changing expected routing outcomes.
- Avoid adding new diagnostic output.
- Avoid adding actual runtime identifiers to test output or assertions.

## 6. Keep-as-is Items

Keep:

- sanitized routing-log regression assertions
- assertions that runtime markers are absent from logged values
- logger patches that suppress expected framework or router noise
- CSRF negative-test warning suppression
- fail-closed warning coverage
- permission-stage `side_effect` controls
- placeholder test modules for now
- broader expected-warning capture design for later

## 7. Deferred Items

- placeholder test module cleanup
- broader expected warning capture redesign
- cleanup of logger patches that currently suppress expected framework or router noise
- any change that affects mock setup, failure injection, routing, session, authorization, CSRF, or fail-closed assertions
- W342 model warning cleanup
- Level 2 controlled write/upload smoke
- tenant metadata repair for non-selectable groups
- broad AdminKit-derived template cleanup

## 8. Verification Plan

After future implementation, run:

| command | expected result |
|---|---|
| `python -m py_compile control/test_group_search_login_fix.py` | passed |
| `python manage.py test control.test_group_search_login_fix` | 16 tests OK |
| `python manage.py test control.test_tenant_connection_registration` | 29 tests OK |
| `python manage.py check` | passed with existing W342 warning only |
| `git diff --check` | passed |
| `Test-Path geoflow_ops/templates/geoflow_ops/excel_preview.html` | False |
| `Test-Path geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` | False |

Browser smoke:

- Not required for this design task.
- Not required after future implementation unless runtime code is unexpectedly touched.

## 9. Out of Scope

- No implementation in this design task.
- No code or test modification in this design task.
- No production diagnostic cleanup.
- No production code change.
- No routing behavior change.
- No session behavior change.
- No tenant-candidate behavior change.
- No DB connection registration change.
- No authentication or authorization change.
- No template or static change.
- No migration.
- No DB write.
- No endpoint call.
- No browser smoke.
- No S3 or presigned URL operation.
- No Level 2 write/upload smoke.
- No W342 cleanup.

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
