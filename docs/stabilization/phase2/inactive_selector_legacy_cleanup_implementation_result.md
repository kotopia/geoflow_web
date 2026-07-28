# Inactive Selector Legacy Cleanup Implementation Result

## 1. Baseline

- Branch: phase2-clean-base
- Design commit: 90754b3 phase2: design inactive selector legacy cleanup
- Implementation commit: dfe0fc2 phase2: remove inactive tenant selector middleware
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Remove the legacy inactive `TenantSelectorMiddleware`.
- Preserve active tenant routing middleware behavior.
- Avoid changing middleware registration, routing, session behavior, tenant candidate behavior, authentication, authorization, settings, tests, templates, static files, migrations, or DB state.

## 3. Modified File

- `control/middleware.py`

Implementation scope:

- No tests were modified.
- No settings file was modified.
- No `geoflow_ops` file was modified.
- No templates or static files were modified.
- No migrations were added or changed.
- No DB schema or data code path was intentionally changed.

## 4. Implementation Summary

- The `TenantSelectorMiddleware` class definition was removed.
- The removed class had been classified as legacy inactive.
- It was not registered in active `MIDDLEWARE`.
- It had no runtime import or invocation.
- It had no direct test dependency.
- No replacement middleware was added.
- No new logging was added.
- `TenantMiddleware` was preserved.
- `CentralGuardMiddleware` was preserved.
- `EnsureTenantAliasMiddleware` was preserved.
- `TENANT_PATH_PREFIXES` was preserved.
- `MiddlewareMixin` import was preserved because active middleware still uses it.
- Active middleware order and settings registration were not changed.

## 5. Removed Legacy Code

| file | removed item | treatment |
|---|---|---|
| `control/middleware.py` | `TenantSelectorMiddleware` class definition | removed |
| `control/middleware.py` | active middleware classes | unchanged |
| `control/middleware.py` | shared constants/imports required by active middleware | unchanged |

## 6. Verification Result

| command | result |
|---|---|
| `python -m py_compile control/middleware.py` | passed |
| `python manage.py test control.test_group_search_login_fix` | 16 tests OK |
| `python manage.py test control.test_tenant_connection_registration` | 29 tests OK |
| `python manage.py check` | passed with existing W342 warning only |
| `git diff --check` | passed |
| `Test-Path geoflow_ops/templates/geoflow_ops/excel_preview.html` | False |
| `Test-Path geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` | False |

- Existing W342 warning remains unrelated.
- No browser smoke was performed for this legacy-code-removal-only implementation.
- No unexpected traceback or test failure was observed.

## 7. Behavior Preservation

- No active middleware behavior was changed.
- No middleware registration was changed.
- No central route handling was changed.
- No tenant route handling was changed.
- No central guard redirect behavior was changed.
- No tenant alias session behavior was changed.
- No scope session behavior was changed.
- No fail-closed tenant connection behavior was changed.
- No thread-local routing state behavior was changed.
- No group selection behavior was changed.
- No post-login routing behavior was changed.
- No permission behavior was changed.
- No DB connection registration behavior was changed.
- No authentication or authorization behavior was changed.
- No project settings were changed.

## 8. Safety Status

- No DB write was performed.
- No migration was performed.
- No tenant schema change was performed.
- No endpoint call was performed.
- No browser smoke was performed.
- No S3 operation was performed.
- No presigned URL was generated.
- No sensitive runtime identifier was recorded.
- `excel_preview.html` remains absent.
- `thumbnail-utils.js` remains absent.

## 9. Deferred Items

- unrelated test-only diagnostic cleanup
- W342 model warning cleanup
- Level 2 controlled write/upload smoke
- tenant metadata repair for non-selectable groups
- broad AdminKit-derived template cleanup

## 10. Safety Notes

- No code or test was modified by this documentation task.
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

## 11. Conclusion

- Inactive selector legacy cleanup implementation is complete.
- The unused `TenantSelectorMiddleware` class was removed.
- Active tenant routing middleware remains unchanged.
- Control route regression tests passed.
