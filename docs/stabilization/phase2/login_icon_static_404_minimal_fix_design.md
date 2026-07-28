# Login Icon Static 404 Minimal Fix Design

## 1. Baseline

- Branch: `phase2-clean-base`
- Current HEAD: `6f74679 phase2: analyze login icon static 404`
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define a narrow fix for the non-blocking `/login/` icon static 404.
- Replace the stale relative icon path in the login template with Django static resolution.
- Reuse the existing static icon asset.
- Avoid changing login behavior, authentication, tenant routing, settings, middleware, static assets, or unrelated templates.

## 3. Root Cause Summary

- The login template uses a relative icon path.
- When the page is loaded at `/login/`, the browser resolves the relative path under `/login/`.
- The requested path returns HTTP 404.
- The icon asset already exists under the Django static asset path.
- Maintained base and partial templates already use Django `{% static %}` for the same icon.
- Therefore, the issue is a stale relative template reference, not a missing asset or static configuration failure.

## 4. Minimal Implementation Scope

Allowed future implementation file:

- `control/templates/control/login.html`

Expected change:

- Replace the relative icon reference with `{% static 'control/img/icons/icon-48x48.png' %}`.

Do not change:

- login view logic
- authentication logic
- tenant candidate logic
- tenant routing
- central routing
- middleware
- router
- `settings.py`
- `urls.py`
- static files
- AdminKit-derived unrelated templates
- favicon or manifest handling outside the confirmed login reference
- DB or migrations

## 5. Expected Verification

After the future implementation, run:

| command | result expected |
|---|---|
| `git diff --check` | passed |
| `python manage.py check` | passed with existing W342 warning only |
| read-only `/login/` browser smoke | login page HTTP 200 and icon 404 not observed |
| read-only login smoke | login still routes correctly |

No Python syntax check is required if the implementation remains template-only.

## 6. Browser Smoke Scope After Fix

Allowed after implementation and explicit approval:

- fresh `--noreload` runserver
- start from `/login/`
- confirm the login page loads
- confirm no `/login/...icon...` 404 appears
- perform a read-only login route check
- do not intentionally create, edit, delete, upload, download, or trigger write flows

## 7. Out of Scope

- No implementation in this design step
- No browser smoke in this design step
- No static asset creation
- No broad AdminKit template cleanup
- No diagnostic log cleanup
- No W342 cleanup
- No Level 2 write/upload smoke
- No DB or S3 operation

## 8. Safety Notes

- No code or template was modified by this design task.
- No static file was modified or created.
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
