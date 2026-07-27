# Post Phase 2 Single-tenant Read-only Smoke Result

## 1. Baseline

- Branch: `phase2-clean-base`
- Current HEAD: `c3dd937 phase2: plan single tenant readonly smoke`
- Working tree expected state before smoke: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Smoke Type

- Single-tenant read-only browser smoke
- Fresh `--noreload` runserver
- Browser flow started from `/login/`
- No intentional create, edit, upload, delete, migration, tenant provisioning, or permission provisioning was performed
- No intentional S3 or presigned upload operation was performed

## 3. Login and Tenant Routing Result

- Existing runserver processes were checked before starting.
- The working tree was clean before smoke.
- The browser started from `/login/`.
- Single-tenant login completed successfully.
- The group-selection page was not shown.
- This is expected because a single selectable tenant candidate routes directly to the tenant workflow under Option A.
- The post-login flow routed to the tenant workflow.
- The tenant home/main page returned HTTP 200.

## 4. Contracts Read-only Result

- The contracts list returned HTTP 200.
- The contracts list rendered without a server error.
- One existing contract detail page was opened read-only.
- The existing contract detail returned HTTP 200.
- No contract create, edit, save, or delete action was performed.

## 5. Events Read-only Result

- The existing contract-scoped event list was loaded by the existing contract detail page.
- The event list request returned HTTP 200.
- The event modal UI was opened read-only.
- The event modal returned HTTP 200.
- No event create, edit, save, or delete action was performed.

## 6. Uploads, Inline Previews, and Static Assets

- No file upload was performed.
- No attachment delete was performed.
- No intentional file download was performed.
- Existing upload-related JavaScript assets loaded on tenant pages.
- Existing inline attachment or profile preview behavior triggered presign-get GET requests automatically during page rendering.
- This was not an intentional upload, delete, or write operation.
- This did not create, modify, or delete DB rows.
- This did not perform a presigned upload operation.
- The Excel preview page was not used.
- `excel_preview.html` remains absent.
- `thumbnail-utils.js` remains absent.

## 7. Observed Non-blocking Static Warning

- A login-page icon path returned HTTP 404.
- This did not block login, tenant routing, contracts, contract detail, event list, or event modal smoke.
- This is a non-blocking static asset path issue and is deferred.

## 8. Error Check

| check | result |
|---|---|
| clean HEAD before smoke | yes |
| fresh `--noreload` runserver | yes |
| `/login/` start | yes |
| single-tenant login | completed |
| group-selection page | not shown as expected |
| tenant home/main | HTTP 200 |
| contracts list | HTTP 200 |
| existing contract detail | HTTP 200 |
| contract-scoped event list | HTTP 200 |
| event modal UI | HTTP 200 |
| `ConnectionDoesNotExist` | not observed |
| `ImproperlyConfigured` | not observed |
| unexpected traceback | not observed |
| intentional create/edit/delete/upload | no |
| intentional DB write | no |
| intentional S3/presigned upload operation | no |
| automatic existing inline presign-get GET | observed |
| `excel_preview.html` | absent |
| `thumbnail-utils.js` | absent |

## 9. Not Performed

- No code change
- No DB write
- No migration
- No schema change
- No tenant provisioning
- No permission provisioning
- No contract create, edit, or delete
- No event create, edit, or delete
- No file upload
- No attachment delete
- No intentional file download
- No intentional presigned upload operation
- No template or static change
- No `settings.py` change

## 10. Safety Notes

- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext or decrypted personal data was printed.
- No actual user email, group name, group UUID, tenant alias, connection alias, DB host, DB password, DB configuration value, contract UUID, event UUID, attachment ID, S3 key, presigned URL, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 11. Conclusion

- Post-Phase-2 single-tenant read-only smoke passed.
- Single-tenant direct routing is expected and consistent with Option A.
- Tenant home/main, contracts list, existing contract detail, event list, and event modal read-only workflows returned HTTP 200.
- No blocking tenant-routing, contract, event, or upload-related read-only regression was observed.
- Existing inline preview behavior triggered presign-get GET automatically, but no intentional upload, delete, DB write, or presigned upload operation was performed.
- Level 2 controlled write/upload smoke remains deferred and requires separate explicit approval.
