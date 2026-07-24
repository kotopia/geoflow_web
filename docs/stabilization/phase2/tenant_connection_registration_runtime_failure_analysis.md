# Tenant Connection Registration Runtime Failure Analysis

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: ff32b49 phase2: document tenant connection registration smoke failure
- Working tree expected state: clean

## 2. Observed Symptom

- The tenant connection registration implementation was committed.
- Browser smoke was retried.
- Tenant workflow access still failed with `ConnectionDoesNotExist`.
- The literal connection alias is not recorded.
- Single-tenant confirmation was not completed.
- No successful smoke result is claimed.

## 3. Static Flow Review

- The project URL configuration routes `/after-login/` to `post_login_redirect()`.
- `post_login_redirect()` first reads tenant and group state from the session.
- Central or incomplete selection state continues through the existing central redirect without tenant preparation.
- For tenant state, `post_login_redirect()` calls `ensure_tenant_connection_for_session()` before issuing the tenant-page redirect.
- Helper success preserves the existing tenant redirect.
- Helper failure:
  - Replaces the tenant alias session state with central state.
  - Replaces the compatibility database key with central state.
  - Removes selected group and role session state.
  - Redirects to the safe central dashboard.
- The post-login helper and redirect logs use generic route or failure messages and do not include tenant aliases or group identifiers.
- Separate tenant middleware logging still includes resolved routing metadata. That existing log hygiene concern is distinct from the helper's safe failure messages.

Static inspection confirms that the intended `/after-login/` path calls connection preparation before tenant redirection and fails safely when preparation returns false.

## 4. Registry Mutation Review

- The helper checks `connections.databases` before central configuration lookup.
- An already registered alias returns success without mutation.
- A missing alias is accepted only after active central membership, active group configuration, completeness, and alias-match checks.
- A valid configuration is written to runtime `settings.DATABASES`.
- The same configuration is also written to `connections.databases`.
- Django's connection handler exposes its configured database-settings mapping through `connections.databases`.
- Mutating that active mapping should make the alias available to later `connections[alias]` lookups in the same server process.
- Connection wrapper instances are cached separately from the database-settings mapping, but a previously unused alias has no wrapper that must be replaced. The handler can create one when the alias is first requested.
- Runtime registration is process-local. It does not persist across a server restart and is not shared with a different worker or stale runserver process.
- In a single current runserver process, a successful registry mutation should normally remain visible to the following redirected request.
- The test suite replaces settings and the connection handler with mocks. Its `DATABASES` override warning reflects test isolation mechanics and does not prove real runtime persistence or failure.

The static registry behavior does not reveal an obvious reason that a successful mutation would disappear between two requests handled by the same current process. That makes process freshness, flow bypass, or helper failure important alternatives.

## 5. Middleware and Direct Access Review

- Tenant middleware runs on every non-control request.
- It reads the tenant alias directly from session state and writes it into request-local tenant routing state.
- It does not verify that the alias exists in `connections.databases`.
- It does not invoke tenant connection preparation.
- The database router returns the request-local alias for tenant application models.
- A direct tenant-page request can therefore reach ORM routing with an unregistered session alias.
- Reloading a previous tenant error page can bypass `/after-login/` entirely.
- A stale browser session can retain an alias from an earlier failed run or an older server process.
- The central guard only distinguishes central from tenant state; it does not validate connection registration.
- Middleware-level defensive preparation could close this bypass before tenant ORM work, provided it reuses the same authenticated session and central configuration checks.
- Such preparation does not require tenant database writes and must not weaken group candidate authorization.
- To avoid import cycles and duplicate policy, the connection preparation logic should be moved into a small lower-level control helper that both `/after-login/` and tenant middleware can call.

## 6. Failure Possibilities

### 1. Stale browser session or direct reload

- This is plausible because a tenant URL can be requested directly with an unregistered alias retained in session.
- That path does not pass through `/after-login/`.

### 2. Runserver not restarted or not using the latest code

- This is plausible when an old process remains active or the retry targets a different process.
- Runtime registry changes and code loading are process-local.

### 3. `/after-login/` not reached before tenant page access

- This is plausible for direct navigation, reload, bookmarks, or an incomplete browser sequence.
- Static code cannot confirm which route the failed smoke actually traversed.

### 4. Helper reached but central configuration lookup failed

- This remains possible because missing membership, inactive group state, missing configuration, incomplete fields, or an alias mismatch all return failure.
- The intended result in that case is a safe central redirect, not `ConnectionDoesNotExist`.
- Observing `ConnectionDoesNotExist` instead suggests either the safe redirect was bypassed or the running process did not execute the current helper path.

### 5. Helper registered the alias but mutation did not persist

- This is less likely within one current runserver process because both active settings mappings are mutated.
- It remains possible across different processes or workers because runtime registration is not shared.
- A runtime trace using sanitized boolean milestones would be needed to prove helper success and subsequent registry visibility.

### 6. Tenant middleware or router needs defensive preparation

- This is a confirmed structural gap for direct tenant access.
- Middleware currently trusts the session alias before checking registry availability.

### 7. Selected tenant configuration is incomplete or inactive

- This is possible and should continue to fail closed.
- It must not be addressed by weakening validation or adding a static environment-specific alias.

## 7. Most Likely Next Fix Direction

Based on static findings:

- First repeat the smoke with a fully stopped and freshly started server, a fresh login session, and navigation beginning at `/login/`.
- Confirm that `/after-login/` is traversed rather than reloading an existing tenant URL.
- If the failure persists under that discipline, add defensive connection preparation in tenant middleware.
- Extract the existing preparation logic into a lower-level control helper to avoid circular imports and policy duplication.
- Middleware should invoke that helper before setting a non-central request-local tenant alias or before any downstream tenant ORM access.
- Preparation must use only authenticated session-selected group state and central configuration.
- Missing or invalid configuration must clear or reject tenant context and redirect safely.
- Candidate validation and HTTP 403 behavior must remain intact.
- Do not add a static environment-specific alias to `settings.py`.

## 8. Proposed Future Test Plan

DB-free or mocked tests should verify:

1. A direct tenant-page request with session tenant state triggers defensive preparation before router use.
2. An already registered alias remains a no-op.
3. A missing alias with valid mocked central configuration is registered before middleware sets tenant context.
4. Missing or invalid configuration clears tenant context or redirects safely.
5. An arbitrary request payload alias is ignored.
6. Existing `/after-login/` preparation remains intact.
7. Group candidate validation remains intact.
8. The known single-tenant alias flow remains intact.
9. No tenant database write occurs.
10. Existing authorization, upload, contract, and event tests continue to pass.
11. Middleware does not log sensitive connection or identity values on failure.

## 9. Recommended Manual Smoke Discipline

- Stop all runserver processes completely.
- Start one fresh runserver process from the current clean HEAD.
- Use logout or a fresh browser session.
- Begin at `/login/` rather than reloading a tenant URL.
- Perform one multi-tenant selection.
- Confirm that `/after-login/` is traversed.
- Verify that the tenant page returns HTTP 200.
- Perform single-tenant smoke separately.
- Record only sanitized results.

## 10. Out of Scope

- Actual code fixes.
- Database migrations.
- Database writes.
- Tenant provisioning.
- Permission provisioning.
- Static alias additions in `settings.py`.
- Event, upload, or delete workflows.
- S3 or presigned URL work.
- Secret or personally identifiable information inspection.

## 11. Safety Notes

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
