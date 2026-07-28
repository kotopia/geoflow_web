# Login Icon Static 404 Read-only Smoke Result

## 1. Baseline

- Branch: `phase2-clean-base`
- Current HEAD: `0c7b5b6 phase2: document login icon static fix`
- Smoke type: narrow read-only browser-path smoke
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Confirm that the `/login/` icon static 404 fix works in read-only smoke.
- Confirm that `/login/` still loads normally.
- Confirm that the old `/login/...icon...` 404 is no longer observed.
- Confirm that read-only login entry routing remains unchanged.

## 3. Smoke Scope

- A fresh `--noreload` runserver was used.
- Smoke started from `/login/`.
- Only read-only login, static asset, HTML structure, and unauthenticated routing checks were performed.
- No login credentials were submitted.
- No create, edit, delete, upload, download, DB write, S3, or presigned URL flow was intentionally triggered.
- The development server was stopped after verification.

## 4. Result Summary

| check | result |
|---|---|
| `/login/` page load | passed |
| login page HTTP status | 200 |
| old `/login/...icon...` 404 | not observed |
| static icon request | resolved with HTTP 200 |
| login form visible | passed |
| CSRF/form structure intact | passed |
| style and script references present | passed |
| read-only login entry routing | passed |
| authenticated login submission | not performed |
| unexpected traceback | none observed |
| unexpected write flow | none observed |

The rendered shortcut-icon reference used the Django static URL rather than the previous login-relative path.

## 5. Observed Logs

- The login page loaded.
- The shortcut icon loaded through the static asset path.
- The static icon 404 under `/login/` was not observed.
- The unauthenticated root request followed the existing redirect behavior.
- No unexpected traceback was observed during the successful smoke.
- No raw runtime or identifying log values are recorded in this document.

## 6. Verification Commands

| command | result |
|---|---|
| `python manage.py runserver 127.0.0.1:8000 --noreload` | started |
| `/login/` read-only smoke | passed |
| Django static icon GET | HTTP 200 |
| unauthenticated read-only root routing | redirect resolved |
| `Test-Path geoflow_ops/templates/geoflow_ops/excel_preview.html` | False |
| `Test-Path geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js` | False |

## 7. Conclusion

- The login icon static 404 fix is verified by read-only smoke.
- `/login/` returned HTTP 200.
- The icon resolved through the Django static path with HTTP 200.
- The former login-relative icon request was not generated.
- Login form, CSRF field, style, and script structure remained present.
- Authenticated login submission was intentionally outside this narrow static-path smoke.

## 8. Safety Notes

- No code or template was modified by this smoke task.
- No static file was modified or created by this smoke task.
- No DB write was performed.
- No migration was performed.
- No create, edit, delete, upload, or download flow was executed.
- No S3 access was performed.
- No presigned URL was generated.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext or decrypted personal data was printed.
- No actual user email, group name, group UUID, tenant alias, connection alias, DB host, DB password, DB configuration value, contract UUID, event UUID, attachment ID, S3 key, presigned URL, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
