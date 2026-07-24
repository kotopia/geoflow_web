# EnsureTenantAliasMiddleware Hardening Implementation Result

## 1. Baseline

- Branch: phase2-clean-base
- Design commit: 6631a03 phase2: design ensure tenant alias middleware hardening
- Implementation commit: 49c98a4 phase2: harden ensure tenant alias middleware
- Working tree expected state: clean

## 2. Purpose

- `TenantMiddleware` now owns normal tenant routing context preparation.
- `EnsureTenantAliasMiddleware` previously remained as a later fallback.
- Static analysis found that fallback alias assignment could reintroduce unregistered aliases.
- This implementation hardens `EnsureTenantAliasMiddleware` so it cannot set an unregistered tenant alias.
- This document records the implementation result only.

## 3. Modified Files

- control/middleware.py
- control/test_tenant_connection_registration.py

## 4. Implementation Summary

- `EnsureTenantAliasMiddleware` was changed to pass-through behavior.
- It no longer reads a tenant alias from session state.
- It no longer calls `_set_threadlocal()` or an equivalent tenant context setter.
- It no longer writes an unregistered tenant alias into router-visible request-local context.
- If `TenantMiddleware` already established request-local context, the fallback leaves that context unchanged.
- If request-local context is empty, the existing central fallback behavior remains.
- `TenantMiddleware` remains the primary owner of tenant routing context.
- `/after-login/` connection preparation remains unchanged.
- Group candidate HTTP 403 validation remains unchanged.
- Request payload and URL alias values are not used.
- The static `settings.py` file was not modified.
- No tenant DB business-data write is performed.

## 5. Test Result

| test command | result |
|---|---|
| `python manage.py test control.test_tenant_connection_registration` | 25 tests OK |
| `python manage.py test control.test_group_search_login_fix` | 10 tests OK |
| `python manage.py test geoflow_ops.test_attachment_delete_authorization` | 12 tests OK |
| `python manage.py test geoflow_ops.test_upload_write_csrf` | 7 tests OK |
| `python manage.py test geoflow_ops.test_upload_presign_get_read_authorization` | 9 tests OK |
| `python manage.py test geoflow_ops.test_contract_write_permission` | 6 tests OK |
| `python manage.py test geoflow_ops.test_event_write_permission` | 9 tests OK |
| `python manage.py check` | passed with existing W342 warning only |

- The only existing check warning was `catalog.CategoryParent.child` W342.
- DB-free tests used mocks and skipped real database setup.
- The `DATABASES` override warning was observed only in mocked test context and is unrelated to production DB writes.
- `git diff --check` passed.
- `py_compile` passed.

## 6. Not Performed

- No browser smoke was performed.
- No real login endpoint was called.
- No real after-login endpoint was called.
- No real group selection endpoint was called.
- No real contracts endpoint was called.
- No DB write was performed.
- No migration was performed.
- No schema change was performed.
- No tenant provisioning was performed.
- No permission provisioning was performed.
- No event, upload, or delete endpoint was called.
- No S3 access was performed.
- No presigned URL was generated.
- No template or static file was changed.
- No `settings.py` file change was made.

## 7. Follow-up Recommendation

- Commit this implementation result document first.
- The next step should be an explicitly approved browser smoke.
- Browser smoke must use:
  - all development-server processes stopped
  - one fresh development server from current clean HEAD
  - logout or a fresh browser session
  - `/login/` as the starting point, rather than a reloaded tenant workflow error page
- Browser smoke should verify:
  - multi-tenant login reaches group selection without `NoReverseMatch`
  - only authorized tenant candidates are shown
  - selecting one authorized candidate reaches the tenant home or tenant workflow page with HTTP 200
  - `ConnectionDoesNotExist` is not observed
  - single-tenant login still reaches the tenant home with HTTP 200
- Smoke documentation must remain sanitized.

## 8. Safety Notes

- No code was modified by this documentation task.
- No DB write was performed by this documentation task.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated or printed.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext was printed.
- No decrypted personal data was printed.
- No user email, name, or phone number was recorded.
- No UUID, group identifier, tenant alias, candidate list, or raw identifier was recorded.
- No literal connection alias from an error page was recorded.
- No DB host, password, or configuration value was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
