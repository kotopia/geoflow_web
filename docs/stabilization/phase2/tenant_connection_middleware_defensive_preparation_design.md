# Tenant Connection Middleware Defensive Preparation Design

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 73e4e8d phase2: analyze tenant connection registration runtime failure
- Working tree expected state: clean

## 2. Purpose

- `/after-login/` already prepares the tenant connection before normal tenant redirect.
- Browser smoke still observed `ConnectionDoesNotExist`.
- Runtime analysis identified possible direct tenant-page access, stale session reuse, page reload, or middleware and router use of a session alias before preparation.
- This document defines a defensive middleware-level preparation step.
- No code or database change is performed in this task.

## 3. Design Principle

- Keep the existing `/after-login/` preparation.
- Add defense in depth before middleware or the router establishes tenant database context.
- Do not weaken group candidate validation.
- Do not accept aliases from request payload or URL parameters.
- Use only authenticated session state and central group configuration.
- Keep already registered aliases as a no-op.
- Fail closed for missing, inactive, incomplete, unauthorized, or mismatched configuration.
- Do not add static aliases to `settings.py`.
- Do not run migrations.
- Do not perform tenant database business-data writes.

## 4. Proposed Fix Location

Recommended:

- Tenant middleware should call the same connection preparation logic before setting the request-local tenant database alias.
- If the current helper is too closely coupled to a view, move its lower-level logic into a small reusable control helper.
- `/after-login/` and middleware should both call that lower-level helper.
- Middleware must not duplicate central configuration lookup and validation independently.

Middleware defense is needed because:

- Direct access to a tenant page can bypass `/after-login/`.
- A browser reload can reuse old tenant session state.
- A fresh runserver process does not retain aliases registered in an earlier process.
- The database router depends on request-local alias state and fails when that alias is absent from the active connection registry.

## 5. Proposed Helper Refactor

The existing helper can remain named `ensure_tenant_connection_for_session(request)`, or its responsibilities can be split into small functions such as:

- `prepare_tenant_connection_from_session(request)`
- `clear_tenant_session_state(request)`
- `is_tenant_connection_registered(alias)`

Expected behavior:

1. Read selected tenant and group state from the session.
2. Determine whether the flow is central or tenant.
3. Return success immediately for central flow.
4. Return success without mutation for an already registered alias.
5. Resolve missing alias configuration through the authenticated selected group and central configuration.
6. Validate membership, active group state, completeness, and exact alias match.
7. Register a valid runtime alias idempotently.
8. Return failure without exposing configuration details when validation fails.
9. Never use a request payload or URL alias.
10. Never log database host, password, configuration, or identifying alias values.
11. Perform no tenant database business-data write.

## 6. Middleware Behavior

- Before setting a non-central request-local database alias, middleware checks whether session state indicates tenant flow.
- With no tenant session state, middleware continues its existing central behavior.
- With tenant session state, middleware invokes the defensive preparation helper.
- On success, middleware sets request-local tenant context exactly as before.
- On failure, middleware:
  - Clears or replaces unsafe tenant routing session state with central state.
  - Clears request-local tenant context.
  - Prevents the router from receiving an unregistered alias.
  - Redirects to a safe central, login, or controlled error flow according to current middleware style.
- It must not raise a raw `ConnectionDoesNotExist`.
- It must not expose alias or configuration values in logs.
- Central and explicitly exempt paths should avoid unnecessary preparation work.

## 7. Safety and Authorization Constraints

- Middleware must not register arbitrary aliases.
- The selected group must remain tied to the authenticated session.
- Central group database configuration must be active and complete.
- Session alias and central configuration alias must match exactly.
- Existing `group_select` HTTP 403 validation remains unchanged.
- Runtime registration must not overwrite an existing alias with conflicting configuration.
- Failure must be controlled and sanitized.
- Static `settings.py` alias addition remains prohibited.

## 8. Proposed Code Scope

A future implementation should be limited to:

- `control/views_auth.py`
- The active tenant middleware file
- Optionally one small helper module under `control`
- `control/test_tenant_connection_registration.py`, or one focused DB-free middleware test file

Avoid:

- `settings.py` file modification
- Migrations
- `geoflow_ops` changes
- Template or static changes
- URL changes unless strictly necessary
- Tenant database application code changes

## 9. Proposed Test Plan

DB-free or mocked tests should verify:

1. Middleware does nothing for central or no-tenant session state.
2. Middleware reuses an already registered alias without mutation.
3. Middleware registers a missing alias with valid mocked central configuration before setting router-visible tenant context.
4. Middleware fails closed on missing configuration.
5. Middleware fails closed on incomplete configuration.
6. Middleware fails closed on inactive configuration.
7. Middleware clears or prevents unsafe tenant context on failure.
8. Middleware ignores request payload aliases.
9. Existing `/after-login/` preparation still works.
10. Invalid group candidate selection still returns HTTP 403.
11. The known single-tenant alias flow still works.
12. No tenant database write occurs.
13. Existing authorization, upload, contract, and event tests still pass.

Tests should mock:

- Session state
- Central membership and configuration lookup
- `settings.DATABASES`
- `connections.databases`
- The request-local tenant context setter

Tests must not use a real central database, tenant database, group row, alias, password, host, endpoint, or browser.

## 10. Browser Smoke Plan After Implementation

Only after implementation and commit, with explicit approval:

- Stop all runserver processes completely.
- Start one fresh runserver process from the current clean HEAD.
- Use logout or a fresh browser session.
- Begin at `/login/`, not a reloaded tenant URL.
- Perform multi-tenant login.
- Confirm that the group selection page loads without `NoReverseMatch`.
- Confirm that only authorized tenant candidates are displayed.
- Select one authorized candidate.
- Confirm that the tenant home or tenant workflow page returns HTTP 200.
- Confirm that `ConnectionDoesNotExist` is not observed.
- Confirm separately that single-tenant login reaches the tenant home with HTTP 200.

Do not record user email, group identifier, tenant alias, connection alias, candidate list, UUID, raw identifier, group name, database host, password, or configuration.

## 11. Risk Analysis

- Middleware runs frequently, so the helper must remain narrow, idempotent, and safe.
- Accidental database writes in middleware are unacceptable.
- Repeated preparation of an already registered alias must be a no-op.
- Failing open would recreate `ConnectionDoesNotExist` or allow unsafe routing.
- Registering arbitrary aliases would be unsafe.
- Leaking database configuration would be unsafe.
- Static settings alias additions do not scale.
- Browser smoke must avoid stale sessions and old error-page reloads.

## 12. Out of Scope

- Actual code fixes.
- Database migrations.
- Database writes.
- Tenant provisioning.
- Permission provisioning.
- Static alias additions in `settings.py`.
- Event, upload, or delete workflows.
- S3 or presigned URL work.
- UI redesign.
- Secret or personally identifiable information inspection.

## 13. Safety Notes

- No code was modified.
- No database write was performed.
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
- No UUID, group identifier, tenant alias, candidate list, raw identifier, or literal connection alias was recorded.
- No database host, password, or configuration value was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
