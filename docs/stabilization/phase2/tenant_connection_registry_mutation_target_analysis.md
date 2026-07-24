# Tenant Connection Registry Mutation Target Analysis

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: e4fae75 phase2: document ensure tenant alias middleware smoke failure
- Working tree expected state: clean

## 2. Observed Runtime Symptom

- A fresh development server was started from the clean worktree.
- The group selection page was reached.
- Tenant candidate selection was completed.
- Tenant workflow access still failed with `ConnectionDoesNotExist`.
- The debug page showed that tenant middleware was configured.
- The debug page showed ORM access attempted through an unregistered selected connection.
- No successful smoke result is claimed.

No actual user, group, tenant, connection, UUID, database, or raw identifier is recorded.

## 3. Current Helper Registry Mutation Review

`ensure_tenant_connection_for_session()` builds runtime connection configuration only after all of the following checks:

- the selected route is non-central
- required authenticated session state exists
- the selected alias is not already registered
- the authenticated central user can be resolved
- active central membership exists
- an active central group configuration exists
- the configured alias matches the authenticated session selection
- required connection configuration fields are complete
- a central base configuration is available

The helper derives a new configuration dictionary from the central base configuration and replaces the engine and connection-specific fields with values from the authorized central configuration.

After construction, the helper currently writes the new entry to:

- `settings.DATABASES`
- `connections.databases`

It does not explicitly assign through `connections.settings`. It also does not verify `connections[alias]` availability after registration before returning success.

The existing warning for configuration lookup failure is sanitized. It does not include an alias, group identifier, connection value, or exception detail.

## 4. Django ConnectionHandler Lookup Findings

Local installed-source inspection found:

- Django version: 5.2.4
- `connections` is an instance of `django.db.utils.ConnectionHandler`.
- `ConnectionHandler.__getitem__()` is implemented in `django/utils/connection.py`, beginning at line 56 in the installed Django source.
- `ConnectionHandler.settings` is a `cached_property`.
- `ConnectionHandler.databases` is a backward-compatibility property that returns `self.settings`.

The effective lookup flow is:

1. Check the thread-local connection cache for an existing wrapper.
2. If no wrapper exists, check whether the requested alias is a key in `self.settings`.
3. Raise `ConnectionDoesNotExist` when that key is absent.
4. Otherwise create and cache a connection wrapper for that alias.

The settings property configures `self._settings` once and caches the returned dictionary. Local DB-free introspection established that, in the current process:

- `settings.DATABASES`
- `connections.databases`
- `connections.settings`

all reference the same dictionary object. Numeric memory identifiers were inspected only to establish identity and are not recorded here.

A standalone DB-free `ConnectionHandler` check also established that mutating the original dictionary after the settings property had been cached remained visible through `handler.settings`. No connection was opened.

Therefore:

- mutating `settings.DATABASES` in place is visible to the active handler when it retains the same dictionary object
- mutating `connections.databases` is currently equivalent to mutating `connections.settings`
- writing both `settings.DATABASES` and `connections.databases` is redundant in the observed Django 5.2 process
- a separate direct mutation of `connections.settings` is not necessary in this observed object topology

This conclusion depends on in-place mutation of the same dictionary. Replacing `settings.DATABASES` with a different dictionary after the handler has cached its settings would not automatically replace the handler's cached object.

### Can the Helper Report Success While Lookup Still Fails?

The current static implementation writes into the same registry dictionary checked by `ConnectionHandler.__getitem__()`. On that basis, the simple wrong-registry-target hypothesis is not supported by local introspection.

However, the helper does not perform a post-registration handler lookup or membership assertion before returning success. A runtime mismatch could therefore remain undetected if:

- the browser request reaches a different process or settings instance
- another path replaces rather than mutates a settings dictionary
- the helper branch is not reached
- helper success is mocked or altered in another runtime path
- the selected value differs from the registered key due to shape or normalization differences
- state is changed between preparation and ORM routing

Calling `connections[alias]` creates a Django connection wrapper but does not itself execute a business-data query. A carefully scoped future verification can therefore validate handler availability without opening a tenant cursor or transaction.

## 5. Router Fail-closed Review

`control.db_router.TenantRouter`:

- routes central applications directly to the central alias
- obtains the alias for tenant applications from `current_db_alias()`
- returns that alias for reads and writes
- does not check active handler registry membership before returning it

If request-local state contains an unregistered alias, Django subsequently calls `connections[alias]`, and `ConnectionHandler.__getitem__()` raises `ConnectionDoesNotExist`.

A router-level defense can be useful as a secondary invariant check, but it must not silently route tenant business operations to the central database. Returning no tenant alias could allow Django's default routing fallback to select the central database, which would be unsafe for tenant business models.

If added, a router guard should fail closed with a controlled configuration exception or an equivalent explicit failure. Primary prevention should remain in connection preparation and middleware before tenant context becomes router-visible.

## 6. Root Cause Hypothesis

- The original `group_search` reverse issue is not the current failure.
- Candidate rendering and HTTP 403 validation are not the current failure.
- Tenant middleware is present in static configuration.
- Local Django introspection shows that the helper mutates the same dictionary checked by `ConnectionHandler.__getitem__()`.
- The current evidence therefore does not support a simple `connections.databases` versus `connections.settings` split as the root cause.

The more likely remaining possibilities are:

- the helper is not executed in the failing browser process or branch
- the browser reaches a different server process or settings instance
- the helper returns success without a post-registration handler-availability check
- request-local routing context is established using a value that is not present in the active process registry
- runtime state changes between registration and contract ORM access

The failure is not proven to be migration-related.

## 7. Proposed Future Fix Direction

The minimal future direction should be:

1. Keep runtime registration as an in-place mutation of the exact dictionary referenced by the active `ConnectionHandler`.
2. Remove redundant double assignment only if tests prove object identity and behavior remain stable.
3. Immediately after registration, verify membership through the active handler registry.
4. Optionally resolve `connections[alias]` to verify wrapper availability without opening a cursor or executing a query.
5. Return success only after the active handler can resolve the registered alias.
6. Make `TenantMiddleware` set router-visible tenant context only after that verification succeeds.
7. On failure, clear tenant session and request-local state and remain central.
8. Consider a router invariant guard that raises a controlled configuration error for an unregistered tenant alias.

The router guard must never silently redirect tenant application reads or writes to the central database.

Group candidate HTTP 403 validation must remain unchanged. No environment-specific alias should be added statically to `settings.py`, and no migration is required.

## 8. Proposed Test Plan

DB-free mocked tests should verify:

1. The helper mutates the same registry checked by Django's connection handler.
2. After helper registration, the alias is visible to the mocked active connection handler.
3. A post-registration handler lookup can resolve a wrapper without executing a query.
4. Handler verification failure causes the helper to return failure.
5. Helper failure does not set router-visible tenant context.
6. Middleware sets tenant context only after actual registry membership verification.
7. The router does not return an unregistered tenant alias.
8. An already registered alias remains a no-op.
9. Invalid or incomplete configuration fails closed.
10. Post-login preparation remains intact.
11. `TenantMiddleware` behavior remains intact.
12. `EnsureTenantAliasMiddleware` remains pass-through.
13. Invalid group candidate selection continues to return HTTP 403.
14. Existing authorization, upload, contract, and event tests continue to pass.

Tests must use mocks and must not access a real central or tenant database.

## 9. Out of Scope

- Actual code changes
- Database migration or write
- Tenant provisioning
- Static `settings.py` alias additions
- Browser smoke
- Login, post-login, group-selection, contract, event, upload, or delete endpoint calls
- S3 access or presigned URL work
- Secrets or personal-data inspection

## 10. Safety Notes

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
