# Tenant Connection Registration Fix Design

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: ef7e779 phase2: analyze tenant connection registration issue
- Working tree expected state: clean

## 2. Purpose

- Multi-tenant group search routing and candidate rendering issues have been addressed.
- Browser smoke now reaches post-selection tenant routing.
- The remaining failure is `ConnectionDoesNotExist`.
- A selected tenant alias can be stored in session before the Django runtime has registered that alias.
- This document defines a minimal future fix.
- No code or database change is performed in this task.

## 3. Design Principle

- Do not add environment-specific aliases statically to `settings.py`.
- Do not weaken group selection candidate validation.
- Do not run migrations.
- Do not perform tenant database writes.
- Prepare the tenant database connection before redirecting to tenant pages.
- Keep the central/default database as the source for tenant connection configuration.
- Missing, inactive, or incomplete tenant database configuration must fail safely.

## 4. Proposed Fix Location

Recommended:

- Introduce a small reusable tenant connection preparation helper.
- Call it from `/after-login/` before redirecting to tenant pages.
- Reuse an existing registered alias without mutation.
- Register a missing alias only after resolving the selected group's central database configuration.
- Keep this behavior centralized rather than duplicating it in login and group selection.

`/after-login/` is preferred because:

- Both single-tenant and multi-tenant flows pass through it.
- It is the final boundary before routing to tenant pages.
- It can stop tenant routing before middleware or the database router receives an unregistered alias on a subsequent tenant request.
- It provides one consistent preparation and safe-failure point.

## 5. Proposed Helper Behavior

A helper such as `ensure_tenant_connection_for_session(request)`, or a similarly named helper in the existing control authentication or tenant-routing area, should:

1. Read the selected group and tenant session state.
2. Determine whether the current flow is central or tenant.
3. Return success without registration for a central flow.
4. Return success without mutation when the selected tenant alias already exists in `connections.databases`.
5. When the alias is missing, load the central database configuration for the selected authenticated group.
6. Validate that the central configuration is active, complete, and tied to the session selection.
7. Build a complete Django database configuration dictionary using the project's confirmed database backend and required defaults.
8. Add the validated alias to `settings.DATABASES` and `connections.databases` only when safe.
9. Return a clear failure result when configuration is missing, inactive, incomplete, unauthorized, or unsupported.
10. Never print database passwords, connection details, or other secrets.
11. Never connect to a real tenant database during unit tests.

## 6. Authorization and Safety Constraints

- The selected group must remain tied to the authenticated user and validated session candidate.
- Do not register an alias supplied through request payload.
- Do not trust URL parameters as a database alias source.
- Resolve configuration through the central group membership and database configuration relationship.
- Confirm that the resolved alias matches the alias associated with the validated session selection.
- Do not expose host, password, alias, UUID, or raw identifiers in logs or documents.
- On failure, redirect to a safe central, login, or controlled error page according to the current application style.
- Connection preparation must not weaken the existing HTTP 403 candidate-selection boundary.

## 7. Runtime Registration Details

- Already registered alias: return success as a no-op.
- Missing alias with valid central configuration: register the validated configuration.
- Missing alias without configuration: fail safely.
- Inactive configuration: fail safely.
- Incomplete configuration: fail safely.
- Unsupported backend: fail safely unless the existing project standard explicitly supports it.
- Session alias and registered alias must match exactly.
- Registration must not overwrite an existing alias with different configuration.
- Preparation must not perform tenant database business-data writes.
- Errors must not include database configuration or credential values.

## 8. Proposed Code Scope

A future implementation should be limited to:

- `control/views_auth.py`, or one small helper module under `control`
- `control/test_group_search_login_fix.py`, or one focused DB-free test file

Avoid:

- Static alias additions in `settings.py`
- Migrations
- Tenant database application changes
- `geoflow_ops` changes
- Template or static changes
- URL changes unless later static inspection proves them necessary

## 9. Proposed Test Plan

DB-free or mocked tests should verify:

1. `/after-login/` reuses an already registered tenant alias without mutation.
2. `/after-login/` invokes connection preparation before tenant redirect.
3. A missing alias with valid central configuration is registered.
4. A missing alias with missing configuration fails safely.
5. A missing alias with incomplete configuration fails safely.
6. An inactive or unsupported configuration fails safely.
7. The helper does not accept arbitrary request-provided aliases.
8. A valid multi-tenant selection remains protected by candidate validation.
9. The known single-tenant alias flow still works.
10. No tenant database write occurs.
11. No `settings.py` file modification is required.
12. Invalid candidate selection still returns HTTP 403.
13. Existing authorization and login tests still pass.

Tests should mock:

- Session state
- Central membership and configuration lookup
- `settings.DATABASES`
- `connections.databases`

Tests must not use a real central database, tenant database, group row, alias, password, or endpoint.

## 10. Browser Smoke Plan After Implementation

Only after implementation and commit, with explicit approval:

- Log out.
- Perform multi-tenant login.
- Confirm that the group selection page loads.
- Confirm that only authorized tenant candidates are displayed.
- Select one authorized candidate.
- Confirm that `/after-login/` prepares the tenant connection.
- Confirm that the tenant home or one tenant workflow page returns HTTP 200.
- Log out.
- Confirm that single-tenant login still reaches the tenant home with HTTP 200.

Do not record user email, group identifier, tenant alias, candidate list, UUID, raw identifier, connection alias, host, or database configuration.

## 11. Risk Analysis

- Registering arbitrary aliases would be unsafe.
- Leaking database configuration in logs or documents would be unsafe.
- Failing to prepare the connection before tenant routing causes `ConnectionDoesNotExist`.
- Static settings alias additions do not scale and are environment-specific.
- Incomplete or conflicting configuration must fail closed.
- An existing registered alias must not be overwritten silently.
- Browser smoke requires carefully sanitized reporting.

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
