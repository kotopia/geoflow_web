# Post Phase 2 Read-only Manual Smoke Result

## 1. Baseline

- Branch: `phase2-clean-base`
- Current HEAD: `9f6fbd3 phase2: plan post checkpoint manual smoke`
- Working tree expected state before smoke: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Smoke Type

- Level 1 read-only browser smoke
- Fresh `--noreload` runserver
- Browser flow started from `/login/`
- No intentional create, edit, upload, delete, or migration operation was performed
- No intentional S3 or presigned upload operation was performed

## 3. Login and Tenant Routing Result

- Initial root access while unauthenticated or central-scoped redirected to the central dashboard as expected.
- The user logged out and restarted from `/login/`.
- Login completed successfully.
- The group-selection page was skipped.
- This is expected under the selected Option A policy because selectable-candidate filtering left one connectable candidate.
- The post-login flow routed to the tenant workflow.
- The tenant home/main page returned HTTP 200.
- This confirms the current policy:
  - zero selectable candidates: central fallback
  - one selectable candidate: direct tenant route
  - two or more selectable candidates: group-selection page
  - non-selectable candidates: excluded from session and UI

## 4. Contracts Read-only Result

- The contracts list page returned HTTP 200.
- The contract list rendered without a server error.
- One existing contract detail page was opened read-only.
- The existing contract detail page returned HTTP 200.
- No contract create, edit, save, or delete action was performed.

## 5. Events Read-only Result

- The existing contract-scoped event list endpoint was loaded by the contract detail page.
- The event list request returned HTTP 200.
- The event modal UI was opened read-only.
- The event modal returned HTTP 200.
- No event create, edit, save, or delete action was performed.

## 6. Uploads and Static Assets

- Existing upload-related JavaScript assets loaded on the contract detail page.
- No file upload was performed.
- No attachment delete was performed.
- No intentional download was performed.
- No intentional presigned URL generation was performed.
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
| multi-membership login | completed |
| group-selection page | skipped as expected under Option A |
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
| intentional S3/presigned URL operation | no |

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
- No S3 access intentionally triggered
- No presigned URL intentionally generated
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

- Post-Phase-2 Level 1 read-only manual smoke passed.
- Tenant direct routing for one selectable candidate is expected and consistent with Option A.
- Contracts list, contract detail, event list, and event modal read-only workflows returned HTTP 200.
- No blocking tenant-routing, contract, event, or upload-related read-only regression was observed.
- Level 2 controlled write/upload smoke remains deferred and requires separate explicit approval.
