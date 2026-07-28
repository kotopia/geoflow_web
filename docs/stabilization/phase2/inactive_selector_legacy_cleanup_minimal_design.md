# Inactive Selector Legacy Cleanup Minimal Design

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 8511ca5 phase2: analyze inactive selector legacy cleanup
- Analysis commit: 8511ca5 phase2: analyze inactive selector legacy cleanup
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define a narrow cleanup for the legacy inactive `TenantSelectorMiddleware`.
- Remove unused legacy middleware code only if implementation confirms no active dependency.
- Preserve active tenant routing middleware behavior.
- Avoid changing middleware registration, routing, session behavior, tenant candidate behavior, authentication, authorization, settings, tests, templates, static files, migrations, or DB state.

## 3. Analysis Summary

- `TenantSelectorMiddleware` is defined in `control/middleware.py`.
- It is not registered in the active `MIDDLEWARE` setting.
- No runtime import or invocation was found.
- No direct test dependency was found.
- Existing documentation reference is historical and not a runtime dependency.
- Activity classification is `legacy inactive`.

## 4. Future Implementation Scope

Allowed future implementation file:

- `control/middleware.py`

Planned implementation:

- Remove only the `TenantSelectorMiddleware` class definition.

Allowed cleanup:

- Remove an import only if it becomes unused after deleting the legacy class.
- Keep imports that are still required by active middleware.

Do not modify:

- `TenantMiddleware`
- `CentralGuardMiddleware`
- `EnsureTenantAliasMiddleware`
- active middleware order
- settings `MIDDLEWARE`
- routing or redirect conditions
- session read/write behavior
- tenant candidate logic
- tenant connection registration
- authentication behavior
- authorization behavior
- tests
- templates or static files
- `settings.py`
- `urls.py`
- migrations

## 5. Import and Shared Code Requirements

- `MiddlewareMixin` must remain if still used by `CentralGuardMiddleware`.
- Shared tenant path constants must remain if still used by `CentralGuardMiddleware`.
- Logger, settings, and thread-local helpers used by active middleware must remain.
- No active middleware class should be edited as part of this cleanup.
- No new logging should be added.

## 6. Behavior Preservation Requirements

A future implementation must not change:

- central route handling
- tenant route handling
- central guard redirect behavior
- tenant alias session behavior
- scope session behavior
- fail-closed tenant connection behavior
- thread-local routing state behavior
- group selection behavior
- post-login routing behavior
- permission behavior
- DB connection registration
- middleware order
- project settings

## 7. Test Design

- No test modification is planned.
- No existing test directly imports, instantiates, or asserts `TenantSelectorMiddleware`.
- Existing control routing tests should pass unchanged.
- Do not weaken any routing, session, fail-closed, or connection registration test.
- Do not add tests unless implementation reveals a direct dependency.

## 8. Verification Plan

After future implementation, run:

| command | expected result |
|---|---|
| `python -m py_compile control/middleware.py` | passed |
| `python manage.py test control.test_group_search_login_fix` | passed |
| `python manage.py test control.test_tenant_connection_registration` | passed |
| `python manage.py check` | passed with existing W342 warning only |
| `git diff --check` | passed |
| `Test-Path geoflow_ops/templates/geoflow_ops/excel_preview.html` | False |
| `Test-Path geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` | False |

Browser smoke:

- Not required for this design task.
- After implementation, a narrow read-only routing smoke may be considered only if there is uncertainty about active middleware behavior.

## 9. Out of Scope

- No implementation in this design task.
- No code or test modification in this design task.
- No active middleware modification.
- No settings modification.
- No routing behavior change.
- No session behavior change.
- No tenant candidate behavior change.
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
