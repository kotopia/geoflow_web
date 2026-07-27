# Post Phase 2 Read-only Smoke Completion Checkpoint

## 1. Baseline

- Branch: `phase2-clean-base`
- Current HEAD: `dc5ed84 phase2: document single tenant readonly smoke result`
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Completed Read-only Smoke Scope

- The post-Phase-2 manual smoke plan was created and committed.
- The multi-membership/selectable-candidate read-only smoke was executed and documented.
- The single-tenant read-only smoke was planned, executed, and documented.
- Both read-only smoke flows passed.
- No Level 2 controlled write/upload smoke has been executed.
- Level 2 remains deferred until separately approved.

## 3. Multi-membership Read-only Smoke Summary

- The browser flow started from `/login/`.
- A fresh `--noreload` runserver was used.
- Login completed successfully.
- One selectable tenant candidate triggered direct tenant routing under Option A.
- The tenant home/main page returned HTTP 200.
- The contracts list returned HTTP 200.
- An existing contract detail returned HTTP 200.
- The contract-scoped event list returned HTTP 200.
- The event modal UI returned HTTP 200.
- `ConnectionDoesNotExist` was not observed.
- `ImproperlyConfigured` was not observed.
- No unexpected traceback was observed.

## 4. Single-tenant Read-only Smoke Summary

- The browser flow started from `/login/`.
- A fresh `--noreload` runserver was used.
- Single-tenant login completed successfully.
- The group-selection page was not shown, as expected.
- The tenant home/main page returned HTTP 200.
- The contracts list returned HTTP 200.
- An existing contract detail returned HTTP 200.
- The contract-scoped event list returned HTTP 200.
- The event modal UI returned HTTP 200.
- `ConnectionDoesNotExist` was not observed.
- `ImproperlyConfigured` was not observed.
- No unexpected traceback was observed.
- Existing inline preview behavior triggered automatic presign-get GET requests during page rendering.
- The automatic presign-get GET behavior was not an intentional upload, delete, DB write, or presigned upload operation.

## 5. Current Routing Policy

| condition | behavior |
|---|---|
| zero selectable candidates | central fallback |
| one selectable candidate | direct tenant route |
| two or more selectable candidates | group-selection page |
| non-selectable candidates | excluded from session and UI |

- Option A remains selected.
- Group selection is not forced when only one selectable candidate remains.
- Non-selectable candidates must not be displayed as selectable choices.
- Session-based `group_select` validation remains required.

## 6. Read-only Smoke Final Status

| area | status |
|---|---|
| multi-membership login | passed |
| single-tenant login | passed |
| tenant home/main | HTTP 200 |
| contracts list | HTTP 200 |
| existing contract detail | HTTP 200 |
| contract-scoped event list | HTTP 200 |
| event modal UI | HTTP 200 |
| `ConnectionDoesNotExist` | not observed |
| `ImproperlyConfigured` | not observed |
| unexpected traceback | not observed |
| intentional create/edit/delete/upload | not performed |
| intentional DB write | not performed |
| intentional S3/presigned upload operation | not performed |
| automatic inline presign-get GET | observed in single-tenant smoke |
| `excel_preview.html` | absent |
| `thumbnail-utils.js` | absent |

## 7. Safety Status

- No DB migration was performed.
- No tenant schema change was performed.
- No static tenant alias was added to `settings.py`.
- No DB provisioning was performed.
- No permission provisioning was performed.
- No contract create, edit, or delete was performed.
- No event create, edit, or delete was performed.
- No file upload was performed.
- No attachment delete was performed.
- No intentional file download was performed.
- No intentional S3 operation was performed.
- No intentional presigned upload operation was performed.
- Excel preview remains removed.
- The thumbnail utility remains absent.

## 8. Deferred Items

- Level 2 controlled write/upload smoke
- broader manual event workflow smoke
- broader manual upload workflow smoke
- login icon static 404 cleanup
- unrelated diagnostic log cleanup
- W342 model warning cleanup
- tenant metadata repair for non-selectable groups

## 9. Recommended Next Work

- The next recommended work is not Level 2 write/upload smoke unless explicitly approved.
- The safer next work is to move to a non-mutating stabilization item.
- The recommended next candidate is planning cleanup of non-blocking diagnostic and static warnings.
- Any write/upload smoke must be separately approved because it may touch the DB and S3.

## 10. Safety Notes

- No code was modified by this documentation task.
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
