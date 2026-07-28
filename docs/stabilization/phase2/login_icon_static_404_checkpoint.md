# Login Icon Static 404 Checkpoint

## 1. Baseline

- Branch: `phase2-clean-base`
- Current HEAD: `b422575 phase2: document login icon static smoke`
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Completed Scope

- Login icon static 404 analysis was completed.
- The minimal fix design was completed.
- The minimal template implementation was completed.
- The implementation result was documented.
- Narrow read-only browser smoke was completed and documented.
- The login icon static 404 item is ready to close.

## 3. Commit Sequence

- `6f74679 phase2: analyze login icon static 404`
- `f2d259b phase2: design login icon static fix`
- `03858cc phase2: fix login icon static path`
- `0c7b5b6 phase2: document login icon static fix`
- `b422575 phase2: document login icon static smoke`

## 4. Root Cause

- The login template previously used a relative shortcut icon path.
- When `/login/` was loaded, the browser resolved that relative path under `/login/`.
- This produced a non-blocking static 404.
- The icon file already existed under the Django static asset path.
- The issue was a stale template reference, not a missing asset or static configuration failure.

## 5. Implementation Summary

Modified file:

- `control/templates/control/login.html`

Implementation state:

- The relative icon reference was replaced with Django `{% static %}` resolution.
- The existing static icon asset was reused.
- No new static asset was created.
- No Python file was modified.
- No settings or URL file was modified.
- No migration was added or changed.
- Login form, CSRF, authentication flow, tenant routing, middleware, and router behavior were not intentionally changed.

## 6. Smoke Verification Result

| check | result |
|---|---|
| `/login/` page load | passed |
| `/login/` HTTP status | 200 |
| old `/login/...icon...` 404 | not observed |
| Django static icon request | HTTP 200 |
| login form visible | passed |
| CSRF/form structure intact | passed |
| style/script structure | passed |
| unauthenticated read-only routing | passed |
| authenticated login submission | not performed |
| unexpected traceback | none observed |
| unexpected write flow | none observed |

- The smoke was intentionally narrow and read-only.
- No credential submission was performed.
- No create, edit, delete, upload, download, DB write, S3, or presigned URL flow was intentionally triggered.

## 7. Safety Status

- No DB write was performed.
- No migration was performed.
- No tenant schema change was performed.
- No S3 operation was performed.
- No presigned URL was generated.
- No static file was added, moved, or modified.
- No broad AdminKit template cleanup was performed.
- `excel_preview.html` remains absent.
- `thumbnail-utils.js` remains absent.

## 8. Deferred Items

- central dashboard medium-risk log cleanup
- fixed route diagnostic level adjustment
- test-only diagnostic cleanup
- W342 model warning cleanup
- Level 2 controlled write/upload smoke
- tenant metadata repair for non-selectable groups
- broad AdminKit-derived template cleanup

## 9. Recommended Next Work

- The login icon static 404 item is closed.
- The next safe work candidate is fixed route diagnostic level adjustment analysis.
- An alternative safe candidate is central dashboard medium-risk log cleanup analysis.
- W342 cleanup should remain deferred unless explicitly selected.
- Level 2 write/upload smoke still requires separate explicit approval.

## 10. Safety Notes

- No code or template was modified by this documentation task.
- No static file was modified or created by this documentation task.
- No DB write was performed.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed by this checkpoint task.
- No S3 access was performed.
- No presigned URL was generated.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext or decrypted personal data was printed.
- No actual user email, group name, group UUID, tenant alias, connection alias, DB host, DB password, DB configuration value, contract UUID, event UUID, attachment ID, S3 key, presigned URL, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
