# EnsureTenantAliasMiddleware Hardening Design

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: f170b69 phase2: analyze tenant middleware runtime path issue
- Working tree expected state: clean

## 2. Purpose

- `TenantMiddleware` now owns normal tenant connection preparation and request-local alias assignment.
- `EnsureTenantAliasMiddleware` remains as a later fallback.
- Static analysis found that the fallback can set request-local alias state without connection-registry validation.
- This document designs minimal future hardening so fallback middleware cannot reintroduce an unregistered alias.

## 3. Design Principle

- `TenantMiddleware` remains the primary owner of tenant routing context.
- `EnsureTenantAliasMiddleware` must not set an unregistered alias.
- Alias values must not be accepted from request payload or URL data.
- Group candidate HTTP 403 validation must not be weakened.
- Environment-specific aliases must not be added statically to `settings.py`.
- No migration is required.
- Missing, incomplete, inactive, or inconsistent configuration must fail closed.
- Logs must use sanitized fixed messages without identifiers or configuration values.

## 4. Proposed Fix Options

### Option A: Make EnsureTenantAliasMiddleware No-op for Tenant Alias Assignment

- This is preferred if tests confirm that `TenantMiddleware` fully owns every normal routing path.
- The fallback may verify or preserve context that is already set.
- It must not independently read session alias state and copy it into request-local context.
- Central and recovery paths remain owned by `TenantMiddleware`.
- Removing duplicate assignment responsibility reduces the chance that a later middleware can bypass connection preparation.

### Option B: Make EnsureTenantAliasMiddleware Reuse the Shared Helper

- Use this option only if a real fallback path remains necessary.
- Call the same tenant connection preparation helper before setting request-local context.
- Set tenant context only after the helper confirms that the connection is ready.
- If preparation fails, clear unsafe tenant session and request-local state and retain central context.
- Never set an alias directly from session state without registry preparation.

### Recommendation

Prefer Option A if DB-free tests confirm that `TenantMiddleware` covers all normal, central, recovery, and post-login paths.

If a fallback path is demonstrably required, use Option B with the same fail-closed behavior as `TenantMiddleware`. Do not maintain an independent, less strict preparation path.

## 5. Proposed Code Scope

Future implementation should be limited to:

- `control/middleware.py`
- `control/test_tenant_connection_registration.py`

Avoid changes to:

- `settings.py`
- `urls.py`
- `geoflow_ops`
- templates or static assets
- migrations
- tenant DB application code

No new routing framework, permission model, or environment-specific configuration should be introduced.

## 6. Proposed Test Plan

DB-free mocked tests should verify:

1. `EnsureTenantAliasMiddleware` does not set an unregistered tenant alias.
2. It no-ops when `TenantMiddleware` has already established request-local context.
3. If fallback behavior remains, it invokes the shared helper before setting context.
4. Helper failure clears unsafe tenant session and request-local context.
5. The router-visible alias is never unregistered after fallback middleware runs.
6. Central and no-tenant requests remain central.
7. Existing `TenantMiddleware` behavior remains intact.
8. Post-login connection preparation remains intact.
9. Invalid group candidate selection continues to return HTTP 403.
10. Existing authorization, upload, contract, and event tests continue to pass.

Tests must use mocks and must not access a real central or tenant database.

## 7. Browser Smoke Plan After Implementation

Only after implementation and commit, with explicit approval:

- stop all development-server processes
- start a fresh development server from clean HEAD
- use a fresh browser session
- start from `/login/`
- verify multi-tenant login, group selection, and tenant workflow access return HTTP 200
- verify `ConnectionDoesNotExist` is not observed
- verify single-tenant login still reaches the tenant home with HTTP 200
- record only sanitized results

## 8. Out of Scope

- Actual code changes
- Database migration or write
- Tenant provisioning
- Static `settings.py` alias additions
- Browser smoke
- S3 access or presigned URL work
- Secrets or personal-data inspection

## 9. Safety Notes

- No code was modified.
- No DB write or migration was performed.
- No endpoint was called and no browser smoke was performed.
- No S3 access or presigned URL work was performed.
- No `.env` contents, `RRN_SYM_KEY`, ciphertext, or decrypted data were printed.
- No user, group, tenant, connection, UUID, or raw identifier was recorded.
- No DB host, password, or configuration value was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
