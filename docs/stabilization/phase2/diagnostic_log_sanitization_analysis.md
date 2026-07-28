# Diagnostic Log Sanitization Analysis

## 1. Baseline

- Branch: `phase2-clean-base`
- Current HEAD: `2ac4a1d phase2: checkpoint readonly smoke completion`
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Identify diagnostic log statements that may expose runtime identifiers or storage paths.
- Separate harmless fixed diagnostic messages from logs that include sensitive or operational identifiers.
- Prepare a narrow future cleanup plan without changing code in this analysis step.

## 3. Background

- Post-Phase-2 read-only smoke passed.
- During smoke, some diagnostic messages printed runtime identifiers.
- Application behavior was not blocked.
- The issue is log hygiene and operational safety, not a functional failure.

No runtime values were collected or recorded for this analysis.

## 4. Log Categories

| category | example type | status |
|---|---|---|
| fixed route diagnostics | `MW: resolved tenant route`, `ROUTER: resolved central route` | generally acceptable |
| failure diagnostics without identifiers | `tenant connection unavailable` | generally acceptable |
| detail diagnostics with alias or ID | contract detail style logs | sanitize candidate |
| upload diagnostics with alias, ID, or object path | presign-get style logs | high-priority sanitize candidate |
| test-only diagnostics | attachment delete test output | lower priority / test-only review |
| static 404 warning | login icon path 404 | separate static cleanup item |

## 5. Findings

| file path | function or area | log label | runtime identifiers included? | risk | recommended action |
|---|---|---|---:|---|---|
| `geoflow_ops/views_uploads.py` | presign-put, commit, presign-get, attachment delete | upload lifecycle labels | yes | high | replace aliases, entity and attachment identifiers, object paths, link identifiers, and user markers with fixed outcome messages |
| `geoflow_ops/views_events.py` | event create, update, and delete | event lifecycle labels | yes | high | remove tenant, event, scope, title, and other record identifiers; retain fixed action and success/failure labels |
| `geoflow_ops/views_contracts.py` | contract detail and edit | `[DETAIL]` | yes | high | remove tenant and contract identifiers; avoid logging serialized form errors and retain only fixed validation status |
| `control/decorators.py` | permission denial | `FORBIDDEN` | yes | high | remove user, group, and full permission-set values; retain a fixed authorization-denied message or a non-identifying permission code only if required |
| `geoflow_ops/views_employees.py` | RRN decryption guard | RRN decryption failure | yes | high | remove the employee identifier; retain only a fixed failure message and a safe exception class when operationally necessary |
| `control/views_users_admin.py` | central dashboard | `CENTRAL_VIEW` | yes | medium | remove session scope and connection identifiers; replace with a fixed central-view message |
| `control/middleware.py` | tenant and central routing | `MW`, `CENTRAL_GUARD` | no | low | fixed messages can remain; consider `logger.debug()` for routine route resolution |
| `control/db_router.py` | database routing | `ROUTER` | no | low | retain sanitized fail-closed warnings; keep normal fixed route messages at debug level |
| `control/views_auth.py`, `control/tenant_connections.py` | post-login and connection preparation | `AUTH`, `POST-LOGIN`, connection failure messages | no | low | retain fixed success/failure messages and avoid adding candidate or connection details |
| `geoflow_ops/test_attachment_delete_authorization.py` and related tests | test diagnostics | test-only output | test markers only | deferred | review separately if test output remains noisy; do not mix with production cleanup |
| login static asset handling | login icon request | static 404 | route only | deferred | handle as an independent static asset task |

No production `print()` call was identified in the inspected diagnostic candidates. The relevant production diagnostics use the project logger.

### Finding Counts

| risk | count |
|---|---:|
| high | 5 |
| medium | 1 |
| low | 3 |
| deferred | 2 |

Counts are by the log areas listed above, not by individual log statement.

## 6. Risk Classification

| risk | meaning | action |
|---|---|---|
| high | logs a storage key, object path, attachment identifier, UUID, tenant identifier, user-related identifier, or potentially detailed form data | sanitize or remove |
| medium | logs route or scope information without secrets but with operational identifiers | sanitize |
| low | fixed message with no runtime identifiers | keep or convert to `logger.debug()` later |
| deferred | unrelated static 404 or test-only output | track separately |

## 7. Recommended Cleanup Plan

A future narrow implementation should:

- Replace runtime-identifier logs with fixed sanitized messages.
- Prefer `logger.debug()` over unconditional informational diagnostics where appropriate.
- Avoid logging tenant or connection identifiers, UUIDs, object or S3 keys, attachment identifiers, contract identifiers, event identifiers, user identifiers, email addresses, phone numbers, or personal data.
- Avoid logging serialized form errors when they may disclose operational field details.
- Keep useful fixed route diagnostics only if needed for development.
- Preserve fixed fail-closed warnings for unavailable tenant connections and router failures.
- Avoid changing behavior, permissions, routing, DB access, upload logic, or templates.
- Add or update tests only if existing tests assert log behavior or a narrow helper is introduced.
- Keep this cleanup separate from the login icon 404 cleanup.

Suggested implementation order:

1. sanitize `geoflow_ops/views_uploads.py`
2. sanitize `geoflow_ops/views_events.py`
3. sanitize `geoflow_ops/views_contracts.py`
4. sanitize permission-denial and employee-decryption guard logs
5. sanitize the central dashboard diagnostic
6. optionally reduce fixed routine route messages to debug level

## 8. Out of Scope

- No code change in this analysis step.
- No log cleanup implementation in this analysis step.
- No static asset fix in this analysis step.
- No DB write.
- No migration.
- No endpoint or browser smoke.
- No S3 or presigned URL operation.
- No Level 2 write/upload smoke.

## 9. Safety Notes

- No code was modified by this analysis task.
- No DB write was performed.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext or decrypted personal data was printed.
- No actual user email, group name, group UUID, tenant alias, connection alias, DB host, DB password, DB configuration value, contract UUID, event UUID, attachment ID, S3 key, presigned URL, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
