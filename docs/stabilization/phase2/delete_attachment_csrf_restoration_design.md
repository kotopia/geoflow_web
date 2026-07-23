# Delete Attachment CSRF Restoration Design

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: e38e24e phase2: record checkpoint after delete attachment smoke test
- Working tree expected state: clean

## 2. Purpose

- `delete_attachment()` is currently the remaining upload write endpoint with `csrf_exempt`.
- The direct delete smoke test has passed.
- This design evaluates whether `@csrf_exempt` can now be removed from `delete_attachment()`.
- This task does not modify code or call the delete endpoint.

## 3. Current Endpoint State

| endpoint | function | method | csrf_exempt? | state-changing? | direct smoke passed? |
|---|---|---|---:|---:|---:|
| `/api/uploads/presign-put/` | `presign_put()` | POST | No | Yes | Yes |
| `/api/uploads/commit/` | `commit()` | POST | No | Yes | Yes |
| `/api/uploads/delete/<uuid>/` | `delete_attachment()` | DELETE | Yes | Yes | Yes |
| `/api/uploads/presign-get/<uuid>/` | `presign_get()` | GET | No | No | Yes |

`delete_attachment()` currently requires login and the DELETE method, resolves the source entity, and performs a soft delete. It still lacks user permission authorization.

## 4. Current Frontend Delete Token Flow

| caller | uses direct delete endpoint? | sends X-CSRFToken? | likely entity type | reload behavior |
|---|---:|---:|---|---|
| `upload-utils.js` `deleteAttachment()` | Yes | Yes | generic attachment | returns JSON to caller |
| `upload-utils.js` `.btn-delete-att` flow | Yes | Yes | rendered attachment | removes matching DOM item |
| `process-events-ui.js` event attachment delete | Yes | Yes | event | reloads event list |
| employee detail direct delete flow | Yes | Yes | employee document | reloads employee detail page |
| contract detail attachment action initialization | Yes, through shared helper | Yes | contract/event attachment | shared action or event list refresh |

The event caller passes the page-level CSRF token into the shared delete helper. The employee caller sends the token in its direct inline DELETE fetch.

## 5. Why CSRF Restoration Is Now Plausible

- The direct delete smoke test passed while `delete_attachment()` was still exempt.
- Known frontend callers already send `X-CSRFToken`.
- `presign_put()` and `commit()` have already had CSRF restored successfully.
- Their previous restoration did not require upload JavaScript or template changes.
- Direct delete can be retested with a disposable event attachment.
- A missing-token middleware test can verify rejection without executing the view body.

## 6. Risks If csrf_exempt Is Removed

- The employee document delete path obtains its token differently from the event attachment path.
- The direct employee DELETE fetch depends on a template-level token source.
- Local HTTP behavior may remain sensitive to Secure CSRF cookie settings.
- `delete_attachment()` is still not user permission-authorized.
- CSRF restoration must not be treated as authorization hardening.
- A token or cookie problem would cause HTTP 403 and prevent deletion; it should not corrupt attachment data.
- Avatar-related delete behavior must not be used for the smoke target because it has additional session fallback logic.

## 7. Recommended Implementation Slice

Recommended limited slice:

- modify `geoflow_ops/views_uploads.py` only
- remove `@csrf_exempt` from `delete_attachment()`
- remove the `csrf_exempt` import because no other function would use it
- do not change delete logic
- do not change authorization logic
- do not change JavaScript
- do not change templates
- do not change `presign_put()`
- do not change `commit()`
- do not change `presign_get()`
- do not touch Excel download-only or PDF inline logic
- no DB or migration change

The expected production diff is limited to the decorator line and the now-unused import line.

## 8. Required Tests After Implementation

Required static and unit tests:

- `python -m py_compile geoflow_ops/views_uploads.py`
- `python manage.py check`
- `python manage.py test geoflow_ops.test_upload_write_csrf -v 2`
- `python manage.py test geoflow_ops.test_upload_presign_get_read_authorization -v 2`

Recommended update to `geoflow_ops/test_upload_write_csrf.py`:

- change the delete resolved-view expectation from exempt to non-exempt
- add a missing-token DELETE request test expecting HTTP 403
- keep the `presign_get()` GET safe-method test

Required browser smoke:

- create a temporary event
- upload a disposable attachment
- confirm presign-put returns HTTP 200
- confirm commit returns HTTP 200
- click delete for the disposable attachment
- confirm direct `/api/uploads/delete/<attachment_id>/` returns HTTP 200
- confirm event list refresh returns HTTP 200
- confirm an existing PDF `presign_get()` returns HTTP 200
- confirm an existing Excel `presign_get()` returns HTTP 200
- confirm `excel_preview.html` remains absent
- confirm `thumbnail-utils.js` remains absent

No actual identifiers, object keys, attachment filenames, or returned URLs should be recorded.

## 9. What Not To Do In This Slice

Do not include:

- delete authorization implementation
- contract write/delete permission mapping
- event source write inheritance
- employee photo delete feature
- orgunit attachment delete
- DB repair
- migration work
- frontend rewrite

## 10. Final Recommendation

Final recommendation: implement a limited slice now.

Reasons:

- the direct delete smoke test passed
- known callers already send the CSRF token
- the prior upload write CSRF restoration succeeded without frontend changes

Keep authorization as a separate follow-up. Use a newly created disposable event attachment for the post-change smoke test and document the result afterward.

## 11. Safety Notes

Confirmed for this design task:

- no code was modified
- no delete endpoint was called
- no DB write was performed
- no S3 access was performed
- no `.env` was read or printed
- no `RRN_SYM_KEY` was read, printed, or changed
- no ciphertext was printed
- no decrypted personal data was printed
- no presigned URL was printed
- no actual UUID, object key, or attachment filename was recorded
- `excel_preview.html` was not recreated
- `thumbnail-utils.js` was not created

