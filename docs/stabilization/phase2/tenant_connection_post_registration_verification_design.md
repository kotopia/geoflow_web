# Tenant Connection Post-registration Verification Design

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: d859d3c phase2: analyze tenant connection registry mutation target
- Working tree expected state: clean

## 2. Problem Summary

- Fresh browser smoke still failed with `ConnectionDoesNotExist`.
- Django middleware configuration included tenant middleware.
- Local Django 5.2.4 introspection showed that `settings.DATABASES`, `connections.databases`, and `connections.settings` are the same dictionary object in the observed process.
- Therefore, the simple wrong-registry-object hypothesis is weak.
- The remaining gap is that the helper does not verify active handler lookup after registration.
- The router also does not fail closed before returning an unregistered tenant alias.

No actual user, group, tenant, connection, UUID, database, or raw identifier is recorded.

## 3. Design Principle

- Runtime tenant registration must remain authorized by central session state and central group DB configuration.
- Tenant aliases must not come from request payload or URL data.
- `TenantMiddleware` remains the normal owner of tenant routing context.
- `EnsureTenantAliasMiddleware` remains pass-through.
- Helper success must mean that the active Django connection handler can resolve the selected alias.
- Middleware must not set router-visible tenant context unless helper verification succeeds.
- The router must not silently fall back tenant business models to the central database.
- No environment-specific alias should be added statically to `settings.py`.
- No migration is required.

## 4. Proposed Helper Verification

Future implementation should update `ensure_tenant_connection_for_session()` so that, after building and registering a tenant connection configuration, it:

1. Confirms alias membership in the active handler registry checked by Django.
2. Verifies that the alias is present in `connections.settings` after registration.
3. Resolves `connections[alias]` inside a controlled `try`/`except` block.
4. Treats `ConnectionDoesNotExist` or an equivalent handler lookup failure as helper failure.
5. Does not open a cursor.
6. Does not execute a tenant query.
7. Does not start a transaction.
8. Does not print the alias or DB configuration values.
9. Removes or avoids exposing an incomplete runtime registration on failure when doing so is safe.
10. Returns success only after active handler lookup succeeds.

`connections[alias]` creates or returns a Django connection wrapper. It should not execute a business-data query by itself. This verifies handler registration only; it does not validate credentials or network connectivity.

Credential and connectivity validation through a real tenant query is outside this minimal fix.

### Already Registered Aliases

An alias already present in the active handler registry should remain a no-op for configuration mutation, but helper success should still be based on handler resolvability. Membership alone must not bypass controlled wrapper lookup if the purpose of this slice is to guarantee the invariant consumed by middleware.

### Verification Failure Cleanup

If the helper inserted a new runtime entry and handler resolution then fails:

- remove only the newly inserted incomplete entry when safe
- do not remove a pre-existing entry
- do not expose the selected alias through request-local routing context
- use only sanitized fixed logging
- return failure so the caller can perform existing fail-closed session cleanup

## 5. Proposed Middleware Behavior

Future `TenantMiddleware` behavior should be:

- call the helper before setting tenant request-local context
- set router-visible tenant alias only when the helper returns success
- if the helper fails:
  - clear tenant-related session keys
  - set the session DB route back to central
  - set request-local context to central
  - redirect to a safe central route
- never set tenant request-local context from a value that has not passed active handler verification
- keep logs sanitized

The current ordering principle remains correct: preparation and verification happen before `_set_threadlocal()` receives tenant context.

## 6. Proposed Router Guard

Add a secondary fail-closed invariant to `control.db_router.TenantRouter` only after the helper and middleware verification path is established.

Design constraints:

- Before returning a tenant alias, verify that it is registered in the active handler registry.
- If it is missing, fail closed with a controlled sanitized configuration error.
- Do not return `None` for tenant application models if that could allow Django to fall back to the central database.
- Do not route tenant business reads or writes to `default`.
- Do not include the actual alias or DB configuration in error messages or logs.

Recommended defense order:

1. Primary prevention: helper post-registration verification.
2. Routing boundary: middleware exposes tenant context only after success.
3. Secondary defense: router rejects an unregistered tenant alias explicitly.

The router guard should expose a stable error category suitable for tests without leaking configuration details.

## 7. Proposed Future Code Scope

Future implementation should be limited to:

- `control/tenant_connections.py`
- `control/middleware.py`
- `control/db_router.py`
- `control/test_tenant_connection_registration.py`

A separate router test file may be added only if needed:

- `control/test_tenant_router_fail_closed.py`

Avoid changes to:

- `settings.py`
- `urls.py`
- `geoflow_ops`
- templates or static assets
- migrations
- tenant DB application code

## 8. Proposed Test Plan

DB-free mocked tests should verify:

1. The helper registers the selected alias in the active handler registry.
2. The helper verifies membership in `connections.settings`.
3. The helper resolves `connections[alias]` after registration without cursor or query execution.
4. The helper returns failure when handler lookup raises `ConnectionDoesNotExist`.
5. A failed newly inserted registration is removed safely.
6. A pre-existing registration is not removed on verification failure.
7. Helper failure prevents middleware from setting router-visible tenant context.
8. Middleware clears unsafe tenant session and context state on helper failure.
9. Middleware sets tenant context only after helper success.
10. An already registered alias remains a configuration no-op and passes handler verification.
11. Invalid or incomplete configuration fails closed.
12. The router raises a controlled sanitized failure for an unregistered tenant alias.
13. The router does not silently route tenant models to the central database.
14. Post-login preparation still works.
15. `TenantMiddleware` behavior remains intact.
16. `EnsureTenantAliasMiddleware` remains pass-through.
17. Invalid group candidate selection continues to return HTTP 403.
18. Existing authorization, upload, contract, and event tests continue to pass.

Tests must use mocks and must not access a real central or tenant database.

## 9. Browser Smoke Plan After Implementation

Only after implementation and commit, with explicit approval:

- stop all development-server processes
- start one fresh development server from current clean HEAD
- use logout or a fresh browser session
- start from `/login/`, not from a reloaded error page
- verify multi-tenant login reaches group selection
- verify authorized candidate selection reaches tenant home or tenant workflow with HTTP 200
- verify `ConnectionDoesNotExist` is not observed
- verify single-tenant login still reaches tenant home with HTTP 200
- document only sanitized results

## 10. Out of Scope

- Actual code changes
- Database migration or write
- Tenant provisioning
- Static `settings.py` alias additions
- Browser smoke
- Login, post-login, group-selection, contract, event, upload, or delete endpoint calls
- S3 access or presigned URL work
- Secrets or personal-data inspection
- Database credential or connectivity validation through a real tenant query

## 11. Safety Notes

- No code was modified.
- No DB write or migration was performed.
- No endpoint was called and no browser smoke was performed.
- No S3 access or presigned URL work was performed.
- No `.env` contents, `RRN_SYM_KEY`, ciphertext, or decrypted data were printed.
- No user, group, tenant, connection, UUID, or raw identifier was recorded.
- No DB host, password, or configuration value was recorded.
- No literal connection alias from an error page was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
