# Test-only Diagnostic Cleanup Analysis

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: ca02cfd phase2: checkpoint inactive selector legacy cleanup
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Analyze remaining test-only diagnostic output.
- Separate intentional test assertions from noisy test-only prints or logger mocks.
- Identify cleanup candidates that do not affect production behavior.
- Prepare a narrow future cleanup plan without changing code or tests in this analysis step.

## 3. Background

- Production high-risk diagnostics were sanitized.
- Fixed normal-route diagnostics were lowered to DEBUG.
- Central dashboard medium-risk diagnostic was removed.
- Legacy inactive middleware was removed.
- Some test-only diagnostic handling may remain.
- This analysis focuses only on tests and test-only diagnostics.
- This is not a production behavior-change task.

## 4. Search Scope

Static inspection covered:

- `control/test_*.py`
- `geoflow_ops/test_*.py`
- placeholder test modules under control and geoflow_ops
- logger patches and logger mock assertions
- direct `print()` and `assertLogs` usage
- mock call inspection and `side_effect` usage
- expected CSRF and fail-closed negative-test paths

No `.env` file was inspected or printed.

## 5. Findings

| file | diagnostic pattern | current behavior | production impact | sensitivity | recommendation |
|---|---|---|---|---|---|
| `control/test_group_search_login_fix.py` | patch of an old logger method in shared login-test setup | patches a normal-route logging method that production code no longer calls after the INFO-to-DEBUG adjustment | none | low | remove the stale patch only |
| `control/test_tenant_connection_registration.py` | logger mock with fixed-message and non-disclosure assertions | verifies that routing diagnostics use a sanitized fixed message and do not include a runtime marker | none | medium | keep |
| `control/test_tenant_connection_registration.py` | logger patch without a log assertion in a router fallback test | suppresses router diagnostic output while the test asserts fail-safe routing behavior | none | low | keep for now; removal offers little value and could reintroduce test noise |
| `geoflow_ops/test_upload_write_csrf.py` | framework logger patch around an expected negative request | suppresses an expected CSRF warning while retaining the HTTP denial assertion | none | low | keep |
| contract and event permission tests | mock `side_effect` used to mark permission-stage passage | controls test flow and is not diagnostic output | none | low | keep; not a cleanup candidate |
| placeholder test modules | generated comments and unused base imports | produce no diagnostic output | none | low | defer as unrelated test-file cleanup |

No standalone `print()` call was found in the inspected test files. No `assertLogs` usage was found.

Expected failure, fail-closed, and framework warning output triggered by negative tests was not classified as removable test-only diagnostic code unless a test explicitly introduced a redundant print or log statement. No such direct statement was found.

## 6. Classification

### 6.1 Keep

Keep:

- the sanitized routing-log regression assertion
- the assertion that a runtime marker is absent from logged values
- logger patches that suppress expected framework or router noise while preserving behavioral assertions
- permission-stage `side_effect` controls
- negative tests that verify HTTP denial or fail-closed behavior

These items either provide regression coverage or prevent expected framework diagnostics from cluttering test output without changing production behavior.

### 6.2 Remove

Remove in a future narrow cleanup:

- the stale login-test patch targeting a logger method that is no longer used by the production normal-route path

The patch has no current assertion value and no longer suppresses the adjusted DEBUG call. Removing only that patch should not change test setup semantics, routing inputs, session expectations, or response assertions.

No standalone test-only `print()` statement was found for removal.

### 6.3 Refactor

No immediate refactor is recommended.

The existing sanitized logger assertion already uses a fixed message and verifies non-disclosure. Rewriting it would provide little benefit and could weaken explicit log-sanitization coverage.

### 6.4 Defer

Defer:

- cleanup of empty placeholder test modules
- broader redesign of expected warning capture
- any change to logger patches that currently suppress expected framework or router output
- any cleanup that would alter mock setup, failure injection, routing, session, authorization, CSRF, or fail-closed assertions

These items are either unrelated to diagnostics or would require a broader test-design decision.

## 7. Recommended Minimal Future Scope

Allowed future implementation file supported by this analysis:

- `control/test_group_search_login_fix.py`

Recommended change:

- Remove only the stale patch of the superseded logger method from the shared login-test patch tuple.

Do not modify:

- production code
- the remaining mocks or login-test setup
- test inputs or candidate data
- routing, redirect, session, status, or fail-closed assertions
- `control/test_tenant_connection_registration.py`
- `geoflow_ops/test_upload_write_csrf.py`
- permission tests
- settings, templates, static files, migrations, or database state

No production impact is expected because the proposed change removes only an unused test mock. If static inspection during implementation reveals that the patch still intercepts an active call, stop and defer rather than broadening the change.

## 8. Verification Plan for Future Implementation

| command | purpose |
|---|---|
| `python -m py_compile control/test_group_search_login_fix.py` | syntax check |
| `python manage.py test control.test_group_search_login_fix` | affected test and login/group selection regression |
| `python manage.py test control.test_tenant_connection_registration` | middleware/router/tenant connection regression |
| `python manage.py check` | Django system check |
| `git diff --check` | diff hygiene |
| `Test-Path geoflow_ops/templates/geoflow_ops/excel_preview.html` | safety check |
| `Test-Path geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` | safety check |

- The affected module is also the core login/group-selection regression module, so one execution satisfies both affected and core coverage.
- The existing W342 warning may remain unrelated.
- Browser smoke is not required for this analysis step.
- Browser smoke is not required for the future test-only cleanup unless implementation unexpectedly touches runtime behavior.

## 9. Out of Scope

- No code change in this analysis step
- No test change in this analysis step
- No production diagnostic cleanup in this step
- No routing behavior change
- No session behavior change
- No tenant-candidate behavior change
- No DB connection registration change
- No authentication or authorization change
- No template or static change
- No migration
- No DB write
- No endpoint call
- No browser smoke
- No S3 or presigned URL operation
- No Level 2 write/upload smoke
- No W342 cleanup

## 10. Safety Notes

- No code was modified by this analysis task.
- No test was modified by this analysis task.
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
