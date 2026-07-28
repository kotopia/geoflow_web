# Central Dashboard Log Cleanup Analysis

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 3a4fde6 phase2: checkpoint fixed route diagnostic levels
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Analyze the previously deferred central dashboard medium-risk diagnostic.
- Identify whether central dashboard or users-admin views still log operational runtime state.
- Classify the sensitivity and noise level of the remaining diagnostic.
- Prepare a narrow future cleanup plan without changing code in this analysis step.

## 3. Background

- High-risk diagnostic logs were already sanitized.
- Fixed normal-route diagnostics were already lowered from INFO to DEBUG.
- The central dashboard diagnostic was intentionally deferred because it may expose operational runtime state.
- This analysis focuses only on central dashboard or user-admin related diagnostics.
- This is not a behavior-change task.

## 4. Search Scope

Static inspection covered:

- `control/views_users_admin.py`
- `control/urls.py`
- central dashboard references in the existing control regression tests
- Python logger and print calls under `control/`, narrowed to the central dashboard and users-admin area

The central dashboard view is implemented in `control/views_users_admin.py` and is registered as the central control entry point in `control/urls.py`. Related regression tests reference the dashboard redirect target, but no test was found that directly asserts the identified dashboard diagnostic message.

No `.env` file was inspected or printed.

## 5. Findings

| file | diagnostic pattern | current behavior | sensitivity | noise level | recommendation |
|---|---|---|---|---|---|
| `control/views_users_admin.py` | central dashboard normal-route diagnostic with routing-state parameters | emits session-derived routing state at INFO whenever the dashboard view is rendered | medium | medium | remove, or replace with a fixed sanitized DEBUG message only if operationally necessary |

One problematic diagnostic was found. It includes session-derived scope and database-routing alias state in a normal-path `INFO` message. These values are operational identifiers that are unnecessary in routine logs and can reveal tenant-routing context.

No other logger or print call was found in `control/views_users_admin.py`. The identified diagnostic is not a failure, fail-closed, security, or authorization message.

## 6. Risk Classification

### 6.1 High Risk

No high-risk central dashboard diagnostic was found. The inspected diagnostic does not directly print credentials, database host/password/configuration, personal information, sensitive encrypted data, an S3 key, or a presigned URL.

### 6.2 Medium Risk

The identified central dashboard diagnostic is medium risk because it prints session-derived routing state, including a database-routing alias, on a normal request path. This information is useful during debugging but unnecessary in routine application logs.

### 6.3 Low Risk

No separate low-risk dashboard diagnostic was found. A future fixed-message-only `DEBUG` diagnostic would be low risk, but the current parameterized `INFO` message is not.

## 7. Recommended Minimal Future Scope

Allowed future implementation file supported by this analysis:

- `control/views_users_admin.py`

Preferred implementation:

- Remove the normal-path dashboard diagnostic because it does not report a failure and has limited operational value.

Acceptable alternative if a dashboard trace is still required:

- Replace it with a fixed sanitized message.
- Lower it to `DEBUG`.
- Do not include session scope, tenant alias, connection alias, user/group identifiers, or other runtime values.

No existing test directly asserts this diagnostic, so no test file change is currently justified. If a future implementation adds a narrow log-sanitization test, that must be separately scoped and must not change dashboard, routing, session, permission, or status behavior.

The future change must not alter:

- central dashboard rendering or response behavior
- login behavior
- tenant or central routing
- session reads or mutation
- permission checks
- templates or static files
- settings or URLs
- migrations, database schema, or database data

## 8. Verification Plan for Future Implementation

| command | purpose |
|---|---|
| `python -m py_compile control/views_users_admin.py` | syntax check |
| `python manage.py test control.test_group_search_login_fix` | login and group-selection regression |
| `python manage.py test control.test_tenant_connection_registration` | routing and connection regression |
| `python manage.py check` | Django system check |
| `git diff --check` | diff hygiene |

- The existing W342 warning may remain unrelated.
- Browser smoke is not required for this analysis step.
- After implementation, a narrow central dashboard read-only smoke may be considered only if there is uncertainty about unchanged rendering behavior.

## 9. Out of Scope

- No code change in this analysis step
- No log cleanup implementation in this analysis step
- No routing behavior change
- No central dashboard behavior change
- No users-admin behavior change
- No permission change
- No settings change
- No migration
- No endpoint call
- No browser smoke
- No S3 or presigned URL operation
- No Level 2 write/upload smoke
- No W342 cleanup
- No inactive selector cleanup

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
