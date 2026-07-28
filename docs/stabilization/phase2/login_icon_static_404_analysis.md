# Login Icon Static 404 Analysis

## 1. Baseline

- Branch: `phase2-clean-base`
- Current HEAD: `fc460bf phase2: checkpoint diagnostic log sanitization`
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Analyze the non-blocking login-page icon static 404 observed during read-only smoke.
- Identify where the icon path is generated or referenced.
- Determine whether the issue is a relative URL, missing static file, template reference, manifest reference, or browser fallback request.
- Prepare a narrow future fix without changing code in this analysis step.

## 3. Observed Symptom

- During `/login/` page load, a request for a login-page icon path returned HTTP 404.
- The issue did not block login.
- The issue did not block tenant routing.
- The issue did not block contracts list, contract detail, event list, or event modal read-only smoke.
- This is classified as a non-blocking static asset path issue.

## 4. Search Scope

The following areas were inspected read-only:

- `control/templates/control/login.html`
- central and tenant base templates
- central and tenant topbar or sidebar partials
- project-level AdminKit-derived templates
- `control/static/`
- project-level `static/`
- `geoflow_ops/static/`
- favicon, shortcut-icon, manifest, and apple-touch-icon references

No settings inspection was required to identify the template-path mismatch.

## 5. Findings

| area | finding | likely relevance |
|---|---|---|
| login template reference | `control/templates/control/login.html` uses the relative reference `img/icons/icon-48x48.png` instead of Django static resolution | high |
| URL resolution | because the reference is relative, a browser loading `/login/` resolves it beneath the login URL path | high |
| static file existence | the requested icon filename already exists in the repository under Django static asset locations | high |
| central and tenant templates | maintained base and partial templates use `{% static 'control/img/icons/icon-48x48.png' %}` for the same icon | high |
| manifest or browser fallback | no relevant manifest or apple-touch-icon reference was found to explain this request | low |
| AdminKit-derived templates | several generic project-level templates retain the same relative AdminKit icon reference | medium, but unrelated to the confirmed login template fix scope |
| canonical and external metadata | AdminKit metadata in the login template is unrelated to the local icon 404 | low |

## 6. Likely Root Cause

The read-only search supports the following root cause:

- The login template explicitly references an icon through a relative URL.
- On `/login/`, the browser resolves that relative URL beneath the current login path.
- The icon file is not missing from the repository; it exists under static asset locations.
- Other maintained central and tenant templates already use Django's `{% static %}` tag for the same asset.
- No manifest-driven or browser-default icon request is needed to explain the observed 404.

Therefore, the likely root cause is a stale AdminKit-style relative icon reference in the login template, not a missing asset or static configuration failure.

## 7. Recommended Fix Direction

A future narrow implementation should:

- Change only the login template icon reference to use `{% static 'control/img/icons/icon-48x48.png' %}`.
- Reuse the existing icon file.
- Avoid adding a duplicate or new icon asset.
- Leave generic AdminKit-derived templates outside the minimal login fix unless separately approved.
- Avoid changing login behavior, authentication, tenant routing, settings, middleware, or unrelated templates.
- Keep this work separate from diagnostic log cleanup and W342 cleanup.

The expected minimal implementation scope is one template reference with no Python, settings, URL, DB, or migration change.

## 8. Verification Plan for Future Fix

| command | purpose |
|---|---|
| `git diff --check` | validate the template-only diff |
| `python manage.py check` | Django system check |
| read-only `/login/` browser smoke | confirm the login page loads and the icon 404 is gone |
| login read-only smoke | confirm login still routes correctly |

No Python syntax check is required if the future change remains template-only. No migration is required.

## 9. Out of Scope

- No code change in this analysis step.
- No static or template fix in this analysis step.
- No DB write.
- No migration.
- No endpoint call.
- No browser smoke.
- No S3 or presigned URL operation.
- No Level 2 write/upload smoke.
- No W342 cleanup.
- No diagnostic log cleanup.
- No broad cleanup of generic AdminKit-derived templates.

## 10. Safety Notes

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
