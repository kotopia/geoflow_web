# Fixed Route Diagnostic Level Adjustment Analysis

## 1. Baseline

- Branch: `phase2-clean-base`
- Current HEAD: `4a96249 phase2: checkpoint login icon static fix`
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Analyze remaining fixed route diagnostic logs after Phase 2 tenant routing stabilization.
- Identify diagnostics that were useful during stabilization but may be too noisy for normal operation.
- Classify each diagnostic as keep as-is, lower to DEBUG, convert to a sanitized logger call, remove later, or defer.
- Prepare a narrow future implementation plan without changing code in this analysis step.

## 3. Background

- Previous read-only and login smoke tests showed expected fixed middleware, router, and login diagnostics.
- These diagnostics helped confirm tenant routing and connection registration behavior.
- High-risk runtime identifier logs were already sanitized separately.
- This analysis focuses on fixed or mostly fixed routing diagnostics that remain visible.
- This is not a behavior-change task.

## 4. Search Scope

The following areas were inspected read-only:

- `control/middleware.py`
- `control/db_router.py`
- `control/views_auth.py`
- `control/views_groups.py`
- `control/tenant_connections.py`
- `control/decorators.py`
- middleware registration names in `geoflow_project/settings.py`
- `control/test_group_search_login_fix.py`
- `control/test_tenant_connection_registration.py`

No production `print()` call was found in the inspected routing, authentication, middleware, router, or tenant-connection areas. The relevant diagnostics use the project logger.

## 5. Findings

| file | diagnostic pattern | current behavior | sensitivity | noise level | recommendation |
|---|---|---|---|---|---|
| `control/middleware.py` | fixed `MW` central/tenant route resolution | INFO on ordinary routed requests | low | high | lower to DEBUG |
| `control/middleware.py` | fixed `MW` tenant connection unavailable | WARNING on fail-closed preparation failure | low | low | keep as-is |
| `control/middleware.py` | fixed central-guard redirect | INFO when central context is redirected away from a tenant route | low | medium | lower to DEBUG |
| `control/middleware.py` | inactive selector's fixed route resolution | INFO if the legacy selector is invoked | low | potentially high | remove later after confirming the legacy class has no external use |
| `control/db_router.py` | fixed `ROUTER` central/tenant route resolution | already DEBUG | low | low | keep as-is |
| `control/db_router.py` | fixed `ROUTER` tenant connection unavailable | WARNING before fail-closed exception | low | low | keep as-is |
| `control/tenant_connections.py` | fixed connection-handler verification failure | WARNING on registry verification failure | low | low | keep as-is |
| `control/tenant_connections.py` | fixed connection-configuration lookup failure | WARNING on authorized configuration lookup failure | low | low | keep as-is |
| `control/views_auth.py` | fixed tenant lookup or eligibility failure | WARNING or exception on central lookup failure | low | low | keep as-is |
| `control/views_auth.py` | fixed multiple-candidate or central-route decision | INFO during expected login decisions | low | medium | lower to DEBUG |
| `control/views_auth.py` | fixed `POST-LOGIN` central/tenant route | INFO during ordinary post-login routing | low | medium | lower to DEBUG |
| `control/views_auth.py` | fixed `POST-LOGIN` tenant connection unavailable | WARNING on fail-closed routing failure | low | low | keep as-is |
| `control/decorators.py` | fixed authorization denial | WARNING on a security-relevant denial | low | low | keep as-is |
| `control/views_users_admin.py` | central dashboard diagnostic | contains operational runtime state | medium | medium | defer to the separately scoped medium-risk cleanup |

All listed fixed messages are sanitized except the separately deferred central dashboard diagnostic. No actual runtime values are recorded here.

## 6. Classification

### 6.1 Keep as-is

Keep the following visible:

- middleware tenant-connection failure warning
- router fail-closed connection warning
- router's existing DEBUG route-resolution message
- connection-handler verification warning
- tenant-configuration lookup warning
- authentication lookup and candidate-eligibility failure warnings
- post-login tenant-connection failure warning
- authorization-denial warning

These messages are failure-only or security-relevant, sanitized, relatively low-noise, and useful for production troubleshooting.

### 6.2 Lower to DEBUG

Lower the following normal-path messages:

- middleware central/tenant route resolution
- central-guard redirect decision
- expected login candidate or central-route decision
- successful post-login central/tenant route decision

These are expected during normal routing and can repeat frequently. They remain useful for troubleshooting but do not need INFO visibility.

### 6.3 Convert to Sanitized Logger Call

No conversion candidate was identified in the inspected scope:

- no relevant production `print()` call was found
- the remaining route diagnostics already use logger calls
- their messages are fixed except for the separately deferred central dashboard item

### 6.4 Remove Later

The inactive `TenantSelectorMiddleware` route diagnostics are removal candidates because:

- the current middleware registration uses `TenantMiddleware`, `CentralGuardMiddleware`, and `EnsureTenantAliasMiddleware`
- the selector class is not registered in the inspected middleware configuration
- removing its diagnostics should be considered only together with a separate decision about the legacy class itself

### 6.5 Defer

Defer the central dashboard diagnostic because it belongs to the previously identified medium-risk cleanup and contains operational state. It should not be mixed into a fixed route level-only implementation.

### Candidate Count Summary

| classification | count |
|---|---:|
| keep as-is | 8 |
| lower to DEBUG | 4 |
| convert to sanitized logger call | 0 |
| remove later | 1 |
| defer | 1 |

Counts are by diagnostic pattern or area in the findings table, not by individual source line.

## 7. Recommended Minimal Future Scope

Recommended future files:

- `control/middleware.py`
- `control/views_auth.py`

Potential test file, only with separate explicit approval:

- `control/test_tenant_connection_registration.py`

Implementation direction:

- Change only normal-path fixed INFO diagnostics to `logger.debug()`.
- Keep failure and security-relevant warnings visible.
- Keep every message fixed and sanitized.
- Do not change conditions, redirects, session state, thread-local state, tenant candidate selection, registry preparation, or router behavior.
- Leave `control/db_router.py` unchanged because its normal route diagnostic is already DEBUG.
- Leave tenant-connection helper warnings unchanged.
- Leave the legacy selector and central dashboard diagnostic for separately scoped work.

Important test dependency:

- An existing tenant-connection test directly asserts the middleware tenant-route diagnostic through `logger.info`.
- Lowering that message to DEBUG would require updating the test expectation.
- If test modification is not explicitly approved, the middleware level adjustment must be deferred rather than leaving a failing test.

## 8. Verification Plan for Future Implementation

| command | purpose |
|---|---|
| `python -m py_compile control/middleware.py control/views_auth.py` | syntax check |
| `python manage.py test control.test_group_search_login_fix` | group selection and login route regression |
| `python manage.py test control.test_tenant_connection_registration` | tenant connection and router regression |
| `python manage.py check` | Django system check |
| `git diff --check` | diff hygiene |

- The existing W342 warning may remain unrelated.
- Browser smoke is not required for this analysis.
- A narrow read-only browser smoke should be considered after a future implementation if middleware diagnostics are changed.

## 9. Out of Scope

- No code change in this analysis step.
- No log-level change in this analysis step.
- No print or logger refactor in this analysis step.
- No routing behavior change.
- No tenant candidate selection change.
- No DB connection registration change.
- No middleware or router behavior change.
- No settings change.
- No migration.
- No endpoint call.
- No browser smoke.
- No S3 or presigned URL operation.
- No Level 2 write/upload smoke.
- No W342 cleanup.
- No central dashboard medium-risk log cleanup.

## 10. Safety Notes

- No code was modified by this analysis task.
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
