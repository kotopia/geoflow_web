# Inactive Selector Legacy Cleanup Checkpoint

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: eb426ff phase2: document inactive selector legacy cleanup
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Completed Scope

- Inactive selector legacy cleanup analysis was completed.
- Minimal design was completed.
- Minimal implementation was completed.
- Implementation result was documented.
- The legacy inactive `TenantSelectorMiddleware` class definition was removed.
- Active tenant routing middleware was preserved.
- Middleware registration was not changed.
- Control route regression tests passed.
- This inactive selector legacy cleanup item is ready to close.

## 3. Commit Sequence

- `8511ca5 phase2: analyze inactive selector legacy cleanup`
- `90754b3 phase2: design inactive selector legacy cleanup`
- `dfe0fc2 phase2: remove inactive tenant selector middleware`
- `eb426ff phase2: document inactive selector legacy cleanup`

## 4. Removed Legacy Code

| file | removed item | final state |
|---|---|---|
| `control/middleware.py` | `TenantSelectorMiddleware` class definition | removed |
| `control/middleware.py` | `TenantMiddleware` | unchanged |
| `control/middleware.py` | `CentralGuardMiddleware` | unchanged |
| `control/middleware.py` | `EnsureTenantAliasMiddleware` | unchanged |
| `control/middleware.py` | `TENANT_PATH_PREFIXES` | unchanged |
| `control/middleware.py` | `MiddlewareMixin` import | preserved |

## 5. Activity Classification

- `TenantSelectorMiddleware` was classified as legacy inactive.
- It was not registered in active `MIDDLEWARE`.
- It had no runtime import or invocation.
- It had no direct test dependency.
- Existing documentation references were historical and not runtime dependencies.

## 6. Verification Summary

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
- No browser smoke was performed because this was a legacy inactive code-removal-only change.
- No unexpected traceback or test failure was observed.

## 7. Behavior Preservation

- No active middleware behavior was changed.
- No middleware registration was changed.
- No active middleware order was changed.
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
- No tests were modified.

## 8. Safety Status

- No DB write was performed.
- No migration was performed.
- No tenant schema change was performed.
- No endpoint call was performed.
- No browser smoke was performed for this checkpoint.
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

## 10. Recommended Next Work

- The inactive selector legacy cleanup item is closed.
- The next safe candidate is unrelated test-only diagnostic cleanup analysis.
- W342 cleanup should remain deferred unless explicitly selected.
- Level 2 write/upload smoke still requires separate explicit approval.
- Any DB, S3, or write flow must require separate explicit approval.

## 11. Safety Notes

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
