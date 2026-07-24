# Tenant Connection Registration Issue Analysis

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 2afa322 phase2: document group search candidate rendering smoke failure
- Working tree expected state: clean

## 2. Observed Symptom

- Multi-tenant login reaches the group selection page.
- Authorized candidate selection proceeds past group selection.
- Post-selection tenant routing is attempted.
- Tenant page access fails with `ConnectionDoesNotExist`.
- The selected tenant database alias is present in session or routing context but is not registered in the active Django connections.

No actual alias, user email, group identifier, UUID, candidate list, raw identifier, or literal connection alias from the error page is recorded.

## 3. Known Working Flow

- The single-tenant branch in `login_view()` stores:
  - `group_uuid`
  - `group_id`
  - `tenant_db_alias`
  - `db_key`
  - `roles`
- The branch copies the database alias returned by the central tenant-membership lookup directly into session state.
- Static settings define the central connection and one known tenant connection.
- No active dynamic connection registration occurs in the single-tenant branch.
- The known single-tenant flow works when its stored alias already matches a connection configured when Django starts.
- Its success therefore does not demonstrate that arbitrary tenant aliases can be registered dynamically.

## 4. Multi-tenant Flow Findings

- `group_select_view()` validates the selected group against the session-stored tenant candidate list.
- For a valid candidate it sets the same principal session keys used by the single-tenant branch, including the selected database alias and compatibility key.
- It then redirects to the project-level `after_login` route.
- `post_login_redirect()` reads the session alias and group state, decides between central and tenant routing, and redirects to the tenant root when tenant state is present.
- `post_login_redirect()` does not verify that the alias exists in `connections.databases`.
- It does not load connection settings or register a missing connection before redirecting.
- Tenant middleware reads the alias from the session and stores it in request-local routing state.
- The middleware also does not register or validate the alias against active Django connections.
- The database router returns that request-local alias for tenant application models.
- When tenant ORM work begins, Django can therefore receive an alias that is not present in the connection registry and raise `ConnectionDoesNotExist`.
- A multi-tenant candidate may reference an alias obtained from central configuration even when that alias was not statically configured at process startup.

## 5. Runtime Connection Registration Findings

Static inspection found:

- Central tenant membership lookup reads a database alias through the central group-to-database configuration relationship.
- A central resolver can inspect group configuration and mapping conventions, but it only returns aliases already present in static Django settings and otherwise falls back to a configured default.
- Static settings contain a fixed central connection and a fixed known tenant connection.
- Middleware and the database router propagate a session alias but do not construct connection settings.
- `/after-login/` does not ensure connection availability.
- A former `_ensure_group_connection()` implementation exists only as commented-out code.
- That inactive code shows an earlier design for reading central database configuration, constructing a Django connection dictionary, and adding it to both settings and `connections.databases`.
- Because the implementation is commented out, it provides no runtime behavior.
- No other active helper was found that:
  - Loads full tenant connection configuration from central metadata.
  - Constructs a Django database configuration dictionary.
  - Adds a missing tenant alias to `connections.databases`.
  - Ensures connection availability before tenant route access.
  - Handles missing or incomplete tenant configuration as a dedicated safe failure.

Static inspection therefore indicates that active runtime tenant connection registration is absent.

## 6. Root Cause Hypothesis

- This is not the original `group_search` reverse issue.
- This is not the candidate rendering issue.
- This is not caused by the HTTP 403 authorization guard.
- It is not proven to be migration-related.
- The most likely cause is missing or skipped runtime tenant database connection registration after multi-tenant group selection.
- An alternative form of the same failure is that the selected candidate references a database alias not configured in the current Django process.
- The failure occurs because session and router state can accept an alias without first ensuring that Django has a corresponding connection definition.

## 7. Fix Options

### Option A: Reuse existing tenant connection registration helper

- This would be preferred if an active, tested helper existed.
- Static inspection found only a commented historical implementation, not a reusable active helper.
- Reviving it verbatim would be unsafe because its configuration, backend, credential handling, and failure behavior require current validation.

### Option B: Move connection preparation into `/after-login/`

- Introduce a small, reusable connection-preparation helper using central configuration.
- Call it from the post-login route before redirecting to tenant pages.
- Verify an already configured alias without changing it.
- For a missing alias, resolve only the authenticated and selected group configuration from the central database.
- Register a complete Django connection configuration before tenant routing.
- Fail safely to a central or explicit error flow when configuration is absent or invalid.
- This provides one preparation point for both single-tenant and multi-tenant paths and reduces duplicated behavior.

### Option C: Add static alias to settings

- This is not recommended.
- It does not scale to multiple tenants.
- It risks committing environment-specific database configuration.
- It leaves the underlying registration gap unresolved.

Recommended:

- Prefer Option B because no active helper is available for Option A.
- Design and test the helper separately before integration.
- Do not modify `settings.py`.
- Do not run migrations.
- Keep group candidate authorization unchanged.

## 8. Proposed Future Test Plan

DB-free or mocked tests should verify:

1. Valid multi-tenant group selection sets the required tenant session state.
2. The selected flow calls tenant connection preparation before redirecting to tenant pages.
3. An already registered alias is reused without mutation.
4. Missing tenant connection configuration fails safely.
5. Connection preparation performs no tenant database write.
6. The single-tenant flow still works.
7. Invalid candidate selection still returns HTTP 403.
8. No static alias addition to `settings.py` is required.
9. No unresolved route names remain.

Tests should mock the central configuration lookup and Django connection registry. They must not connect to a real central or tenant database.

## 9. Out of Scope

- Actual code fixes.
- Database migrations.
- Database writes.
- Tenant provisioning.
- Permission provisioning.
- Static database alias additions in `settings.py`.
- Event, upload, or delete workflows.
- S3 or presigned URL work.
- UI redesign.
- Secret or personally identifiable information inspection.

## 10. Safety Notes

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
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
