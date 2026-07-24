# Tenant Middleware Runtime Path Issue Analysis

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: b6b6ed3 phase2: document tenant connection middleware smoke failure
- Working tree expected state: clean

## 2. Observed Runtime Symptom

- A fresh login flow was retried.
- The group selection page was reached.
- A displayed tenant candidate was selected.
- Tenant workflow access still failed with `ConnectionDoesNotExist`.
- Expected custom middleware and post-login diagnostic logs were not observed in the browser smoke console.
- Static diagnostics confirmed that the intended middleware and helper modules are importable from the current clean worktree.
- No successful browser smoke result is claimed.

No tenant identifier, connection identifier, user identifier, group identifier, database configuration value, or raw identifier is recorded here.

## 3. Static Middleware Order Findings

The relevant request middleware order is:

1. security middleware
2. session middleware
3. common middleware
4. CSRF middleware
5. authentication middleware
6. messages middleware
7. frame-options middleware
8. `control.middleware.TenantMiddleware`
9. `control.middleware.CentralGuardMiddleware`
10. `control.middleware.EnsureTenantAliasMiddleware`
11. authorization-context middleware

Session and authentication middleware run before `TenantMiddleware`, so it can read authenticated user and session state. `TenantMiddleware` runs before both `CentralGuardMiddleware` and `EnsureTenantAliasMiddleware`.

For a normal tenant workflow request, `TenantMiddleware` prepares the connection and sets request-local context before calling the inner middleware chain. `CentralGuardMiddleware` does not set request-local context. `EnsureTenantAliasMiddleware` runs later, but normally sees context already populated and therefore does nothing.

When tenant preparation fails, `TenantMiddleware` returns a redirect without calling its inner middleware chain. Consequently, neither `CentralGuardMiddleware` nor `EnsureTenantAliasMiddleware` runs for that failed request. Under the current order, the later safety middleware cannot restore an unsafe alias in the same request after this failure branch.

## 4. TenantMiddleware Findings

`TenantMiddleware` distinguishes central recovery paths, central control paths, and ordinary application paths.

- Login, static, and media paths set central request-local context without tenant preparation.
- Control paths explicitly set central session and request-local context.
- Other paths read the tenant choice from authenticated session state.
- A non-central choice invokes the shared tenant connection preparation helper before request-local context is set.
- A successful preparation sets the request-local alias and session scope before the view and inner middleware execute.
- A failed preparation clears tenant-related session keys, restores central session state, resets request-local context to central, and returns a redirect immediately.

The current failure branch therefore prevents the router from seeing the failed tenant choice during the remainder of that request. Middleware logs use fixed sanitized messages and do not include dynamic path or identifier values.

One lifecycle limitation remains: request-local storage is thread-local and is overwritten at request entry, but it is not explicitly cleared in a response-finalization block. The active middleware currently sets it on every handled request path, which limits stale reuse, but an explicit request-finalization cleanup would provide stronger isolation.

## 5. EnsureTenantAliasMiddleware Findings

`EnsureTenantAliasMiddleware` is a later fallback. It checks only whether request-local alias state is empty. If it is empty, it reads session state or a configured default and sets request-local state directly.

Static findings:

- It does not call the shared tenant connection preparation helper.
- It does not verify that the selected connection is registered.
- It can write the selected value back to session state.
- It does not independently fail closed when registry preparation is unavailable.
- In the current configured order, it is normally redundant because `TenantMiddleware` has already populated request-local state.
- It does not run after the active `TenantMiddleware` failure branch because that branch short-circuits the inner chain.

Therefore, it is not the confirmed cause of same-request restoration in the observed failure. It remains a defensive gap if it is invoked without prior `TenantMiddleware` ownership, if middleware ordering changes, or if another execution path reaches it with empty request-local state and unsafe session state.

The safest future direction is either to remove its alias-setting responsibility after confirming it is redundant, or to make it reuse the same connection preparation helper and fail-closed cleanup before setting request-local context.

## 6. Router and Request-local Context Findings

Tenant routing state is stored in a module-level `threading.local()` object in `control/middleware.py`.

The relevant functions are:

- `_set_threadlocal()` sets the request-local database alias, central flag, and optional tenant identifier.
- `current_db_alias()` reads the request-local alias and otherwise falls back to the central alias.
- `is_central_request()` reads the request-local central flag.
- `get_current_tenant()` reads the optional request-local tenant identifier.

The database router:

- always routes central applications to the central database
- routes tenant applications using `current_db_alias()`
- does not verify that the returned alias exists in Django's active connection registry
- returns the selected alias for both reads and writes

As a result, if any code path places an unregistered value in request-local storage, the router can return it and Django can raise `ConnectionDoesNotExist`.

For `/contracts/`, the active configured path is:

1. `TenantMiddleware` reads session state.
2. It prepares or verifies the tenant connection.
3. It sets request-local routing context.
4. `CentralGuardMiddleware` checks only whether central access should be redirected.
5. `EnsureTenantAliasMiddleware` normally no-ops.
6. Contract code and the router read the alias set by `TenantMiddleware`.

Thus, in the configured path, `TenantMiddleware` is the component that should establish the router-visible alias. The router itself provides no final registry defense.

## 7. Logging Visibility Findings

The middleware, post-login view, connection helper, and router use Python logging rather than `print`.

Static settings define console handlers for the relevant control loggers at levels that should include middleware information and warning messages during a normal development-server run. The router uses debug-level logging, while middleware and post-login diagnostics use information or warning levels.

The absence of expected messages does not by itself prove that middleware did not execute. Other explanations include:

- the browser reached a different or stale server process
- the active process used different settings or logging configuration
- console output was observed in a different stream or terminal
- the request did not traverse the expected post-login or tenant branch
- server reload behavior left the observed browser request attached to another process

Because static logging configuration appears capable of showing these messages, a fresh-process verification is more useful than assuming branch non-entry from missing console output alone. Any future temporary instrumentation must remain sanitized and should preferably be verified by DB-free tests or captured logger mocks.

## 8. Root Cause Hypotheses

### 1. Browser request reached a different runserver process

This remains plausible because neither expected middleware nor post-login messages were observed despite explicit console logging configuration.

### 2. Middleware executed but logger output was not visible

This is also plausible due to terminal, process, reloader, or settings differences. Missing logs are not conclusive evidence of non-execution.

### 3. TenantMiddleware branch did not enter tenant preparation

Possible if session state was absent, central, cleared, or the request used a recovery path. The exact runtime traversal was not captured.

### 4. TenantMiddleware prepared or cleared state but later middleware restored it

This is not supported for the current failure branch: it returns before later middleware executes. On a normal branch, later fallback logic could matter only if request-local state were unexpectedly empty.

### 5. EnsureTenantAliasMiddleware bypassed registry preparation

The code permits this structurally, but the configured order normally makes it a no-op. It remains a latent risk rather than a confirmed cause.

### 6. Router returned an unregistered alias

This is possible whenever request-local state contains an unregistered value because the router performs no registry validation.

### 7. Central configuration lookup failed and later state was reused

The helper fails closed and `TenantMiddleware` clears state before redirecting. Reuse in the same request is prevented, but stale-process behavior or another alias-setting path still requires runtime-path verification.

## 9. Recommended Next Fix Direction

The next minimal implementation should consolidate ownership of request-local tenant routing:

1. Make `TenantMiddleware` the sole normal owner of request-local tenant alias preparation and assignment.
2. Tighten `EnsureTenantAliasMiddleware` so it either:
   - performs no alias assignment when `TenantMiddleware` owns routing, or
   - invokes the shared preparation helper and the same fail-closed cleanup before assigning context.
3. Ensure every failure path clears both tenant session keys and request-local context.
4. Consider response-finalization cleanup of thread-local state to strengthen request isolation.
5. Add a defensive registry check before any fallback middleware sets tenant context.
6. Consider a fail-closed router defense only as a secondary safety net; it must not silently reroute tenant business operations to the central database.

The group candidate HTTP 403 validation must remain unchanged. No environment-specific alias should be added statically to `settings.py`.

Before implementing, a fresh-runserver diagnostic should establish whether the observed browser request traverses `/after-login/`, the active `TenantMiddleware`, and the shared helper.

## 10. Proposed Test Plan

DB-free mocked tests should verify:

1. `TenantMiddleware` failure prevents later middleware from restoring unsafe tenant context.
2. `EnsureTenantAliasMiddleware` does not set an unregistered tenant choice.
3. The fallback middleware reuses the helper or no-ops when `TenantMiddleware` owns routing.
4. Request-local context is cleared on failure.
5. The router-visible alias is never unregistered after middleware failure.
6. Central and no-tenant requests remain central.
7. An already registered tenant connection remains a no-op.
8. Invalid or incomplete central configuration fails closed.
9. Post-login connection preparation continues to work.
10. Invalid group candidate selection continues to return HTTP 403.
11. Existing authorization, upload, contract, and event tests continue to pass.
12. Request-finalization cleanup prevents request-local state from leaking into the next mocked request.

All tests should use mocks and must not access a real central or tenant database.

## 11. Out of Scope

- Actual code changes
- Database migrations or writes
- Tenant provisioning
- Permission provisioning
- Static `settings.py` alias additions
- Browser smoke
- Login, tenant workflow, event, upload, or delete endpoint calls
- S3 access or presigned URL work
- Secrets or personal-data inspection

## 12. Safety Notes

- No code was modified.
- No DB write was performed.
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
- No UUID, group identifier, tenant identifier, candidate list, or raw identifier was recorded.
- No literal connection identifier from an error page was recorded.
- No DB host, password, or configuration value was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
