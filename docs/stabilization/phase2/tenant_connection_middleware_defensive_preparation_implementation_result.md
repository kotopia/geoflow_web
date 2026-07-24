# Tenant Connection Middleware Defensive Preparation Implementation Result

## 1. Baseline

- Branch: phase2-clean-base
- Design commit: 4a2a95b phase2: design tenant connection middleware preparation
- Implementation commit: 3df322d phase2: prepare tenant connections in middleware
- Working tree expected state: clean

## 2. Purpose

- `/after-login/` tenant connection preparation already existed.
- Browser smoke still showed `ConnectionDoesNotExist`.
- Middleware could still pass a session alias to the router before runtime connection preparation.
- This implementation adds defensive preparation in tenant middleware.
- This document records the implementation result only.

## 3. Modified Files

- control/middleware.py
- control/tenant_connections.py
- control/views_auth.py
- control/test_tenant_connection_registration.py

## 4. Implementation Summary

- Tenant connection preparation logic was extracted into `control/tenant_connections.py`.
- `/after-login/` and `TenantMiddleware` now reuse the same helper logic.
- The active tenant middleware is `control.middleware.TenantMiddleware`.
- Middleware prepares or verifies the tenant connection before setting request-local tenant DB context.
- Central or no-tenant session paths remain central/no-op.
- An already registered tenant alias remains a no-op.
- A missing tenant connection can be registered only through authenticated session state and central group configuration.
- Preparation failure clears unsafe tenant session and context state.
- Middleware prevents the router from receiving an unregistered tenant alias on failure.
- Login, static, and media recovery paths avoid unnecessary tenant preparation.
- Request payload or URL alias is not used.
- Group candidate HTTP 403 validation was not changed.
- The static `settings.py` file was not modified.
- No tenant DB business-data write is performed.

## 5. Log Sanitization

- Dynamic alias and path logging was removed from middleware output.
- `MW: resolved alias=...` style output was removed.
- Middleware now uses sanitized fixed messages only.
- Test coverage verifies that test alias strings are not emitted through middleware logger calls.
- Unrelated existing test output in another module was not changed because it is outside this implementation scope.

## 6. Test Result

| test command | result |
|---|---|
| `python manage.py test control.test_tenant_connection_registration` | 21 tests OK |
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

## 7. Not Performed

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

## 8. Follow-up Recommendation

- Commit this implementation result document first.
- The next step should be an explicitly approved browser smoke.
- Browser smoke should use:
  - a stopped and restarted fresh runserver
  - logout or a fresh browser session
  - `/login/` as the starting point, rather than a reloaded tenant URL
- Browser smoke should verify:
  - multi-tenant login reaches group selection without `NoReverseMatch`
  - only authorized tenant candidates are shown
  - selecting one authorized candidate reaches the tenant home or tenant workflow page with HTTP 200
  - `ConnectionDoesNotExist` is not observed
  - single-tenant login still reaches the tenant home with HTTP 200
- Smoke documentation must remain sanitized.

## 9. Safety Notes

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
