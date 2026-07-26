# Phase 2 Selectable Tenant Candidate Stabilization Checkpoint

## 1. Current HEAD

- Branch: `phase2-clean-base`
- Current HEAD: `65668dc phase2: document selectable tenant candidate smoke result`
- Working tree before this documentation task: clean

## 2. Resolved Problems

- The multi-tenant login flow now resolves the namespaced `group_search` route without the previous `NoReverseMatch`.
- Candidate rendering is limited to authorized candidates stored by the login flow instead of a broad central group listing.
- Eligible tenant connections can be registered at runtime from validated central configuration.
- Tenant middleware performs defensive connection preparation before exposing tenant routing context.
- `EnsureTenantAliasMiddleware` no longer promotes an unregistered session value into request-local tenant context.
- Runtime connection registration is verified against the active Django connection handler before tenant ORM access.
- Database routing fails closed when a requested tenant connection is unavailable instead of silently falling back to the central database.
- Tenant candidates are filtered to selectable candidates before automatic entry or selection-page rendering.

## 3. Final Smoke Result

- The filtered selectable-candidate tenant workflow returned HTTP 200.
- The contracts page returned HTTP 200.
- `ConnectionDoesNotExist` was not observed.
- `ImproperlyConfigured` was not observed.

The smoke result confirms that the selectable-candidate path reached the tenant workflow successfully under the tested conditions.

## 4. Current UX Policy

- When filtering leaves exactly one selectable tenant candidate, the current flow automatically enters that tenant.
- Because of that automatic entry, the group selection page may not be displayed even when the account has multiple raw memberships.
- Candidates that do not satisfy the selectable criteria are not offered as tenant destinations.

## 5. Remaining UX Choice

### Option A: Keep Current Automatic Entry

- Automatically enter the tenant whenever exactly one selectable candidate remains.
- This is the current implemented behavior.
- It minimizes user interaction and avoids presenting unavailable memberships.

### Option B: Show Guidance or Selection for Multiple Raw Memberships

- When multiple raw memberships exist, display an informational or selection screen even if filtering leaves only one selectable candidate.
- This provides clearer feedback that some memberships are currently unavailable.
- It requires a separately approved UX policy and implementation scope.

No change between these options is made by this checkpoint document.

## 6. Safety Confirmation

- No database migration was performed.
- No static tenant alias was added to `settings.py`.
- No tenant database structure was changed.
- No code was modified by this documentation task.
- No database write was performed by this documentation task.
- No endpoint or browser smoke was executed by this documentation task.
- No user email, group identifier, group name, tenant alias, connection alias, database configuration value, or raw identifier is recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
