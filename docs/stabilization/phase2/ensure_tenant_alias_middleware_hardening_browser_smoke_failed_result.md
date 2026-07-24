# EnsureTenantAliasMiddleware Hardening Browser Smoke Failed Result

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 923ee70 phase2: document ensure tenant alias middleware hardening

## 2. Observed Result

- All development-server processes were intended to be stopped, and a fresh runserver was started.
- The server started from the clean worktree.
- A fresh login flow was retried.
- The group selection page was reached.
- A displayed tenant candidate was selected.
- Tenant workflow access was attempted through the contracts page.
- The tenant workflow page did not return HTTP 200.
- `ConnectionDoesNotExist` was observed again.
- The Django debug page showed that the tenant workflow view attempted ORM access through an unregistered selected connection.
- Static middleware configuration shown by the debug page included the tenant middleware entries.
- Single-tenant confirmation was not completed.
- No successful browser smoke result is claimed.

No actual user, group, tenant, connection, candidate, URL, database, UUID, or raw identifier is recorded.

## 3. Interpretation

- The hardening did not yet produce a successful browser smoke result.
- The failure still occurs during tenant database connection resolution.
- This does not reopen the original `group_search` URL reverse issue.
- This does not prove that candidate HTTP 403 validation is wrong.
- This does not prove a migration issue.
- Because the debug page shows tenant middleware is configured, the next analysis should focus on runtime execution and connection-registry mutation.

Likely next investigation points:

- whether `TenantMiddleware` sets request-local tenant alias state even when the helper fails
- whether `ensure_tenant_connection_for_session()` returns success incorrectly
- whether the helper mutates the wrong Django connection-registry object
- whether Django 5.2 `ConnectionHandler` checks `connections.settings` rather than the object currently being mutated
- whether registered aliases appear in `settings.DATABASES` and active connection-handler state before contract ORM access
- whether the router should defensively fail closed when an alias is absent from the active connection registry

## 4. Sanitized Result Table

| step | result |
|---|---|
| fresh development server start | completed |
| fresh login flow | retried |
| group selection page | reached |
| tenant candidate selection | completed |
| contracts workflow access | attempted |
| tenant workflow HTTP 200 | failed |
| observed exception category | ConnectionDoesNotExist |
| middleware configured in settings | yes |
| single-tenant confirmation | not completed |
| successful smoke claimed | no |

## 5. Follow-up Analysis Direction

- Inspect `TenantMiddleware` success and failure branches, focusing on whether request-local context can be set after failed preparation.
- Inspect `ensure_tenant_connection_for_session()` return values and its registry-mutation target.
- Inspect the Django `connections` handler properties used by `__getitem__`.
- Verify whether runtime registration should update `connections.settings` as well as `settings.DATABASES`.
- Add DB-free tests that simulate Django connection-handler lookup after registration.
- Add DB-free tests asserting that middleware never sets a router-visible alias unless it is present in the actual registry checked by Django.
- Consider a router fail-closed guard if a tenant application would otherwise be routed to an unregistered alias.
- Keep group candidate HTTP 403 validation unchanged.
- Do not add static environment-specific aliases to `settings.py`.

## 6. Not Performed

- No code was changed.
- No migration was performed.
- No schema change was performed.
- No tenant DB business-data write was performed.
- No additional endpoint was called by this documentation task.
- No S3 access was performed.
- No presigned URL work was performed.
- No event, upload, or delete workflow was performed.
- No successful browser smoke result is claimed.

## 7. Safety Notes

- No user email was recorded.
- No group identifier or group name was recorded.
- No tenant alias was recorded.
- No connection alias was recorded.
- No tenant candidate list was recorded.
- No UUID or raw identifier was recorded.
- No identifying URL was recorded.
- No DB host, password, or configuration value was recorded.
- No literal connection alias from the error page was recorded.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
