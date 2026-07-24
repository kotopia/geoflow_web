# Tenant Connection Post-registration Verification Implementation Result

## 1. Baseline

- Branch: phase2-clean-base
- Design commit: 4f29fbb phase2: design tenant connection post-registration verification
- Implementation commit: 2f2b414 phase2: verify tenant connection handler registration
- Working tree expected state: clean

## 2. Purpose

- Fresh browser smoke still failed with `ConnectionDoesNotExist`.
- Registry analysis found that the simple wrong-registry-object hypothesis was weak.
- The remaining gap was the lack of active handler lookup verification after runtime registration.
- This implementation strengthens helper success criteria and adds a router fail-closed defense.

## 3. Modified Files

- control/tenant_connections.py
- control/db_router.py
- control/test_tenant_connection_registration.py

`control/middleware.py` was not modified because its existing fail-closed behavior already satisfied this implementation slice.

## 4. Implementation Summary

- `ensure_tenant_connection_for_session()` now verifies alias membership in `connections.settings`.
- The helper resolves `connections[alias]` after registration.
- Wrapper resolution occurs without opening a cursor.
- No tenant query is executed.
- No transaction is started.
- The helper returns success only after active handler lookup succeeds.
- Newly inserted runtime entries are removed when post-registration verification fails.
- Pre-existing runtime entries are not removed on verification failure.
- Middleware fail-closed behavior remains unchanged.
- `EnsureTenantAliasMiddleware` remains pass-through.
- `TenantRouter` now fails closed for unregistered non-central tenant aliases.
- Router fail-closed uses a controlled, sanitized `ImproperlyConfigured` failure.
- Tenant application models are not silently routed to the central database.
- No alias, group identifier, UUID, DB host, password, or configuration value is logged or recorded.

## 5. Test Result

| test command | result |
|---|---|
| `python manage.py test control.test_tenant_connection_registration` | 29 tests OK |
| `python manage.py test control.test_group_search_login_fix` | 10 tests OK |
| `python manage.py test geoflow_ops.test_attachment_delete_authorization` | 12 tests OK |
| `python manage.py test geoflow_ops.test_upload_write_csrf` | 7 tests OK |
| `python manage.py test geoflow_ops.test_upload_presign_get_read_authorization` | 9 tests OK |
| `python manage.py test geoflow_ops.test_contract_write_permission` | 6 tests OK |
| `python manage.py test geoflow_ops.test_event_write_permission` | 9 tests OK |
| `python manage.py check` | passed with existing W342 warning only |
| `python -m py_compile control/tenant_connections.py control/middleware.py control/db_router.py control/test_tenant_connection_registration.py` | passed |

- The only existing check warning was `catalog.CategoryParent.child` W342.
- The `DATABASES` override warning was observed only in mocked test context.
- Unrelated attachment-delete test diagnostic output remains pre-existing and outside this implementation scope.
- `git diff --check` passed.
- No real DB connection, query, write, or migration was performed.

## 6. Not Performed

- No browser smoke was performed.
- No real login endpoint was called.
- No real after-login endpoint was called.
- No real group selection endpoint was called.
- No real contracts endpoint was called.
- No event, upload, or delete endpoint was called.
- No S3 access was performed.
- No presigned URL was generated.
- No DB migration was performed.
- No schema change was performed.
- No tenant provisioning was performed.
- No permission provisioning was performed.
- No `settings.py` change was made.
- No template or static file was changed.

## 7. Follow-up Recommendation

- Commit this implementation result document first.
- The next step should be an explicitly approved browser smoke.
- Browser smoke must use:
  - all development-server processes stopped
  - one fresh development server from current clean HEAD
  - logout or a fresh browser session
  - `/login/` as the starting point
  - no reload of a previous contracts error page
- Browser smoke should verify:
  - multi-tenant login reaches group selection without `NoReverseMatch`
  - authorized candidate selection reaches the tenant home or tenant workflow page with HTTP 200
  - `ConnectionDoesNotExist` is not observed
  - single-tenant login still reaches the tenant home with HTTP 200
- Smoke documentation must remain sanitized.
- If failure persists, the new router fail-closed message category should help distinguish unregistered router state from a lower-level Django `ConnectionDoesNotExist`.

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
