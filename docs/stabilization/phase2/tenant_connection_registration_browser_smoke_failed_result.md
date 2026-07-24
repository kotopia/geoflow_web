# Tenant Connection Registration Browser Smoke Failed Result

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: eb53336 phase2: document tenant connection registration implementation

## 2. Observed Result

- The tenant connection registration implementation had already been committed.
- Browser smoke was retried.
- The multi-tenant flow again reached tenant routing or tenant workflow access.
- The tenant workflow page did not return HTTP 200.
- Django `ConnectionDoesNotExist` was observed again during tenant workflow access.
- The literal connection alias from the error page is not recorded.
- Single-tenant confirmation was not completed in this smoke.
- No successful browser smoke result is claimed.

No actual user email, group identifier, group name, tenant alias, connection alias, candidate list, UUID, raw identifier, identifying URL, database host, database password, or database configuration value is recorded.

## 3. Interpretation

- The tenant connection registration fix did not yet produce a successful browser smoke result.
- The failure still occurs during tenant database connection resolution.
- This does not reopen the original `group_search` `NoReverseMatch` issue.
- This does not prove that candidate authorization is incorrect.
- This does not prove a migration issue.
- The next analysis must distinguish among:
  - A stale browser session or direct reload of an old tenant URL.
  - A runserver process that is not using the latest implementation.
  - `/after-login/` not being reached before tenant page access.
  - The helper being reached but failing to register the alias.
  - Registration being applied to the wrong runtime registry object or not persisting for the tenant request.

## 4. Sanitized Result Table

| step | result |
|---|---|
| implementation committed | completed |
| browser smoke retried | completed |
| tenant routing/workflow access | attempted |
| tenant workflow page HTTP 200 | failed |
| observed exception category | ConnectionDoesNotExist |
| literal connection alias recorded | no |
| single-tenant confirmation | not completed |
| successful smoke claimed | no |

## 5. Follow-up Analysis Direction

- First verify that the next retry uses a fresh runserver process and a fresh login/session.
- Verify that the browser is not merely reloading an existing tenant workflow error page.
- Statically confirm where `post_login_redirect()` invokes the helper.
- Inspect whether the helper mutates both `settings.DATABASES` and the active `connections` registry correctly.
- Inspect whether the connection handler caches database settings before runtime mutation.
- Inspect whether middleware or the database router can receive a session alias before `/after-login/` preparation.
- Consider whether connection preparation also needs to occur defensively in middleware before tenant ORM access.
- Keep candidate validation and HTTP 403 behavior intact.
- Do not add static, environment-specific aliases to `settings.py`.

## 6. Not Performed

- No code was changed.
- No migration was performed.
- No schema change was made.
- No tenant database business-data write was performed.
- No S3 access was performed.
- No presigned URL work was performed.
- No event, upload, or delete workflow was exercised.
- No successful browser smoke result is claimed.

## 7. Safety Notes

- No user email was recorded.
- No group identifier was recorded.
- No tenant alias was recorded.
- No connection alias was recorded.
- No tenant alias candidate list was recorded.
- No UUID or raw identifier was recorded.
- No database host, password, or configuration value was recorded.
- No literal connection alias from the error page was recorded.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
