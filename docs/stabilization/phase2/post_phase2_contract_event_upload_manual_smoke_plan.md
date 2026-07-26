# Post Phase 2 Contracts Events Uploads Manual Smoke Plan

## 1. Baseline

- Branch: `phase2-clean-base`
- Current HEAD: `22ef13b phase2: checkpoint completion`
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Verify the user-facing tenant workflows after Phase 2 stabilization.
- Confirm that contract, event, and upload screens still work in the browser.
- Confirm that Phase 2 login, tenant routing, authorization, CSRF, and upload hardening changes did not break practical workflows.
- Separate read-only smoke from write/upload smoke to avoid accidental DB or S3 mutation.

## 3. Smoke Policy

### Level 1: Read-only Browser Smoke

- Allowed only after explicit approval.
- Uses a fresh `--noreload` runserver.
- Starts from `/login/`.
- Confirms navigation and HTTP 200 pages only.
- Does not create, edit, upload, delete, or intentionally generate new presigned upload URLs.
- May load existing pages and existing static assets.

### Level 2: Controlled Write/Upload Smoke

- Requires separate explicit approval.
- May create a temporary test contract, event, or upload record if needed.
- Must use clearly disposable test records.
- Must clean up created data if the workflow creates anything.
- Must document only sanitized results.
- Must not record real IDs, UUIDs, tenant aliases, DB configuration, S3 keys, presigned URLs, or personal data.

## 4. Proposed Level 1 Read-only Smoke Checklist

| area | check |
|---|---|
| server | stop all existing runserver processes |
| server | start one fresh `python manage.py runserver 127.0.0.1:8000 --noreload` |
| git | confirm clean HEAD before smoke |
| login | start from `/login/` |
| login | multi-membership selectable candidate flow reaches tenant home/main |
| tenant route | `/` returns HTTP 200 |
| contracts | `/contracts/` returns HTTP 200 |
| contracts | contract list page renders without server error |
| contracts | one existing contract detail can be opened if available |
| events | event list or calendar page can be opened if its route is known |
| uploads | existing attachment area renders if available |
| excel | Excel files remain download-only, with no preview page |
| errors | no `ConnectionDoesNotExist` |
| errors | no `ImproperlyConfigured` |
| errors | no unexpected traceback |
| safety | no new data intentionally created |
| safety | no upload or delete intentionally performed |

Exact event and upload routes must be confirmed before execution; this plan does not infer them.

## 5. Proposed Level 2 Controlled Write/Upload Smoke Checklist

This level is deferred until separately approved.

| area | check |
|---|---|
| contract | create a temporary test contract only if approved |
| contract | update the temporary contract only if approved |
| event | create a temporary event under an approved scope only if approved |
| event | update the temporary event only if approved |
| upload | upload a small test file only if approved |
| upload | verify preview or download behavior only if approved |
| delete | delete the temporary attachment only if approved |
| cleanup | remove temporary records and files if created |
| docs | document sanitized results only |

- This level may touch the DB and S3.
- This level must not be run until the user explicitly approves DB and S3 write smoke.
- Test files must be disposable.
- Created records must be identifiable as temporary without exposing real IDs in documentation.

## 6. Required Sanitization

Do not record:

- actual user email
- actual user name or phone number
- group UUID
- group name
- tenant alias
- connection alias
- DB name
- DB host
- DB password
- DB configuration values
- raw IDs
- S3 bucket
- S3 object key
- presigned URL
- attachment ID
- contract UUID
- event UUID
- personal data
- decrypted RRN or ciphertext

## 7. Expected Documentation After Smoke

After an approved Level 1 smoke, create:

- `docs/stabilization/phase2/post_phase2_readonly_manual_smoke_result.md`

After an approved and executed Level 2 smoke, create:

- `docs/stabilization/phase2/post_phase2_write_upload_manual_smoke_result.md`

## 8. Safety Notes

- No code was modified by this planning task.
- No DB write was performed.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext or decrypted personal data was printed.
- No actual user email, group name, group UUID, tenant alias, connection alias, DB host, DB password, DB configuration value, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
