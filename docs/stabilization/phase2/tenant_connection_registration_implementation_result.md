# Tenant Connection Registration Implementation Result

## 1. Baseline

- Branch: phase2-clean-base
- Design commit: 7ae48eb phase2: design tenant connection registration fix
- Implementation commit: 9ee26c2 phase2: register tenant connections before tenant redirect
- Working tree expected state: clean

## 2. Purpose

- Group search routing and candidate rendering fixes now progress to tenant routing.
- The remaining failure was `ConnectionDoesNotExist`.
- This implementation prepares tenant runtime connections before redirecting to tenant pages.
- It avoids static, environment-specific alias additions in `settings.py`.
- It preserves group candidate authorization and HTTP 403 validation.
- This document records the implementation result only.

## 3. Modified Files

- control/views_auth.py
- control/test_tenant_connection_registration.py

## 4. Implementation Summary

- Added `ensure_tenant_connection_for_session()`.
- Central flow returns success without registry mutation.
- An already registered tenant alias returns success without mutation.
- A missing tenant alias is resolved through authenticated session state and central group configuration.
- Active membership and active group database configuration are required.
- Incomplete, inactive, unauthorized, unsupported, or mismatched configuration fails closed.
- The session alias and central configuration alias must match.
- Valid configuration is added to runtime `settings.DATABASES` and `connections.databases`.
- `/after-login/` invokes the helper before tenant redirect.
- If preparation fails, tenant session state is cleared and the user is redirected safely.
- Request payload and URL aliases are not used.
- The static `settings.py` file was not modified.
- Group selection authorization was not weakened.

No actual alias, group identifier, database host, database password, UUID, candidate list, raw identifier, or user email is included.

## 5. Test Result

| test command | result |
|---|---|
| `python manage.py test control.test_tenant_connection_registration` | 12 tests OK |
| `python manage.py test control.test_group_search_login_fix` | 10 tests OK |
| `python manage.py test geoflow_ops.test_attachment_delete_authorization` | 12 tests OK |
| `python manage.py test geoflow_ops.test_upload_write_csrf` | 7 tests OK |
| `python manage.py test geoflow_ops.test_upload_presign_get_read_authorization` | 9 tests OK |
| `python manage.py test geoflow_ops.test_contract_write_permission` | 6 tests OK |
| `python manage.py test geoflow_ops.test_event_write_permission` | 9 tests OK |
| `python manage.py check` | passed with existing W342 warning only |

- The existing `catalog.CategoryParent.child` W342 warning was the only system-check warning.
- DB-free tests used mocks and skipped real database setup.
- A `DATABASES` override warning was observed only in the mocked test context and is unrelated to production database writes.

## 6. Not Performed

- No browser smoke was performed.
- No real login endpoint was called.
- No real after-login endpoint was called.
- No real group selection endpoint was called.
- No real contracts endpoint was called.
- No database write was performed.
- No migration was performed.
- No schema change was made.
- No tenant provisioning was performed.
- No permission provisioning was performed.
- No event, upload, or delete endpoint was called.
- No S3 access was performed.
- No presigned URL was generated.
- No template or static file was changed.
- The `settings.py` file was not changed.

## 7. Follow-up Recommendation

- Commit this implementation result document first.
- The next step should be an explicitly approved browser smoke.
- The browser smoke should verify:
  - Multi-tenant login reaches the group selection page without `NoReverseMatch`.
  - Only authorized tenant candidates are displayed.
  - Selecting one authorized candidate proceeds through after-login.
  - The tenant home or one tenant workflow page returns HTTP 200.
  - `ConnectionDoesNotExist` is not observed.
  - Single-tenant login still reaches the tenant home with HTTP 200.
- Smoke documentation must be sanitized.

## 8. Safety Notes

- No code was modified by this documentation task.
- No database write was performed by this documentation task.
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
- No database host, password, or configuration value was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
