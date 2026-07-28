# Inactive Selector Legacy Cleanup Analysis

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: cc40e3d phase2: checkpoint central dashboard log cleanup
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Analyze whether the legacy `TenantSelectorMiddleware` is still active or referenced.
- Determine whether it is safe to remove later.
- Identify any tests, settings, imports, or comments that still depend on it.
- Prepare a narrow future cleanup plan without changing code in this analysis step.

## 3. Background

- Phase 2 tenant routing stabilization now uses the active middleware path.
- Fixed route diagnostics were already lowered to DEBUG.
- The inactive selector diagnostic was deferred because removing it requires confirming the legacy middleware class has no active use.
- This analysis is read-only and does not change routing behavior.

## 4. Search Scope

Static inspection covered:

- `control/middleware.py`
- the project `MIDDLEWARE` registration in `geoflow_project/settings.py`
- Python imports and references across the project
- control middleware and routing tests
- documentation references needed to distinguish historical commentary from runtime use

No `.env` file was inspected or printed.

## 5. Findings

| area | finding | relevance | recommendation |
|---|---|---|---|
| `control/middleware.py` | `TenantSelectorMiddleware` is defined as a standalone class but is not invoked by another Python runtime component | high | remove in a narrow future cleanup |
| settings middleware list | the active list registers the primary tenant middleware, central guard, and compatibility pass-through; the selector class is not registered | high | keep active registrations unchanged |
| tests | no test imports, instantiates, patches, or directly asserts behavior from the selector class | high | no test modification planned |
| project references | no Python import or runtime reference exists outside the class definition | high | remove the unused definition only |
| documentation | one historical analysis document refers to the selector as inactive and a removal candidate | low | keep as historical documentation; it is not a runtime dependency |

Additional dependency findings:

- `MiddlewareMixin` remains required by `CentralGuardMiddleware`, so its import must remain after selector removal.
- The shared tenant-path prefix constant is used by `CentralGuardMiddleware` and must remain.
- Settings and logger facilities used by active middleware remain required.
- No selector-specific import becomes clearly unused beyond the class definition itself.

## 6. Activity Classification

### 6.1 Active

Not applicable. `TenantSelectorMiddleware` is not registered in the active project middleware list and is not imported or executed by runtime Python code.

### 6.2 Test-only

Not applicable. No direct test dependency was found.

### 6.3 Legacy inactive

`TenantSelectorMiddleware` is classified as **legacy inactive**.

It is defined in `control/middleware.py`, but static inspection found:

- no active middleware registration
- no runtime import or invocation
- no test import or instantiation
- no direct behavior assertion

The remaining documentation reference explicitly treats the class as inactive and does not create a code dependency.

### 6.4 Unclear

Not applicable based on the inspected runtime, settings, test, and project-reference evidence.

## 7. Risk Assessment

- Removing an active middleware would be high risk.
- Removing a test-only helper could require test updates.
- Removing this legacy inactive class has low expected behavior risk because it is neither registered nor referenced.
- Regression tests are still required because the class shares a module with active tenant middleware.
- Any cleanup must leave the active middleware order and tenant-routing behavior unchanged.
- Shared imports and constants required by active middleware must not be removed.

## 8. Recommended Minimal Future Scope

Allowed future implementation file:

- `control/middleware.py`

Recommended change:

- Remove only the `TenantSelectorMiddleware` class definition.
- Remove an import only if a post-removal static check proves that it is unused.

Based on the current inspection:

- Keep `MiddlewareMixin` because `CentralGuardMiddleware` still uses it.
- Keep the tenant-path prefix constant because the central guard still uses it.
- Keep active middleware classes unchanged.
- Do not modify the project middleware registration.
- Do not modify tests because no direct dependency was found.

The future cleanup must not change:

- `TenantMiddleware`
- `CentralGuardMiddleware`
- `EnsureTenantAliasMiddleware`
- active middleware order
- routing or redirect conditions
- session behavior
- tenant-candidate behavior
- tenant-connection registration
- authentication or authorization behavior
- settings, templates, static files, migrations, or database state

## 9. Verification Plan for Future Implementation

| command | purpose |
|---|---|
| `python -m py_compile control/middleware.py` | syntax check |
| `python manage.py test control.test_group_search_login_fix` | login/group selection regression |
| `python manage.py test control.test_tenant_connection_registration` | middleware/router/tenant connection regression |
| `python manage.py check` | Django system check |
| `git diff --check` | diff hygiene |
| `Test-Path geoflow_ops/templates/geoflow_ops/excel_preview.html` | safety check |
| `Test-Path geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` | safety check |

- The existing W342 warning may remain unrelated.
- Browser smoke is not required for this analysis step.
- A narrow read-only routing smoke may be considered after implementation only if removal creates uncertainty about an active runtime path.

## 10. Out of Scope

- No code change in this analysis step
- No legacy class removal in this analysis step
- No active middleware modification
- No settings modification
- No routing behavior change
- No session behavior change
- No tenant-candidate behavior change
- No DB connection registration change
- No authentication or authorization change
- No test modification
- No template or static change
- No migration
- No DB write
- No endpoint call
- No browser smoke
- No S3 or presigned URL operation
- No Level 2 write/upload smoke
- No W342 cleanup

## 11. Safety Notes

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
