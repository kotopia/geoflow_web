# Post Phase 2 Single-tenant Read-only Smoke Plan

## 1. Baseline

- Branch: `phase2-clean-base`
- Current HEAD: `9d11ba4 phase2: checkpoint readonly manual smoke`
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Verify that a single-tenant user can still log in after Phase 2 stabilization.
- Confirm that single-tenant login routes directly to the tenant workflow without group selection.
- Confirm that tenant home/main and read-only tenant pages return HTTP 200.
- Confirm that the selected Option A auto-route policy does not regress single-tenant login.
- Keep the smoke read-only and avoid DB or S3 mutation.

## 3. Scope

This smoke is read-only only.

Allowed after explicit approval:

- fresh `--noreload` runserver
- `/login/` start
- single-tenant login
- tenant home/main page open
- contracts list page open
- one existing contract detail page open if available
- event list or modal opened read-only if loaded by an existing page

Not allowed:

- create
- edit
- save
- delete
- upload
- intentional download
- intentional presigned URL generation
- migration
- tenant provisioning
- permission provisioning

## 4. Expected Routing Behavior

| user/candidate condition | expected behavior |
|---|---|
| single selectable tenant candidate | direct tenant route |
| group-selection page | not expected |
| tenant home/main | HTTP 200 |
| contracts list | HTTP 200 if user has access |
| `ConnectionDoesNotExist` | not observed |
| `ImproperlyConfigured` | not observed |

- This is consistent with Option A.
- Group selection is not required when there is only one selectable candidate.
- Non-selectable candidate handling is not the focus of this smoke because this is a single-tenant flow.

## 5. Proposed Execution Checklist

| area | check |
|---|---|
| server | stop all existing runserver processes |
| server | start one fresh `python manage.py runserver 127.0.0.1:8000 --noreload` |
| git | confirm clean HEAD before smoke |
| login | start from `/login/` |
| login | use a single-tenant test user |
| routing | group-selection page is not shown |
| tenant | tenant home/main returns HTTP 200 |
| contracts | `/contracts/` returns HTTP 200 if authorized |
| contracts | one existing contract detail can be opened read-only if available |
| events | event list or modal can be opened read-only if naturally loaded by the page |
| errors | no `ConnectionDoesNotExist` |
| errors | no `ImproperlyConfigured` |
| errors | no unexpected traceback |
| safety | no create, edit, delete, or upload |
| safety | no intentional DB write |
| safety | no intentional S3 or presigned URL operation |

## 6. Documentation After Smoke

After approved execution, create:

- `docs/stabilization/phase2/post_phase2_single_tenant_readonly_smoke_result.md`

The result document must be sanitized and must not include:

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
- contract UUID
- event UUID
- attachment ID
- S3 key
- presigned URL
- raw IDs
- personal data

## 7. Deferred Items

- Level 2 controlled write/upload smoke
- broader manual event workflow smoke
- broader manual upload workflow smoke
- login icon static 404 cleanup
- unrelated diagnostic log cleanup
- W342 model warning cleanup
- tenant metadata repair for non-selectable groups

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
- No actual user email, group name, group UUID, tenant alias, connection alias, DB host, DB password, DB configuration value, contract UUID, event UUID, attachment ID, S3 key, presigned URL, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
