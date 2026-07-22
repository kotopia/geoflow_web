# Upload Write Endpoint CSRF Restoration Design

## 1. Current Baseline

- Branch: phase2-clean-base
- Baseline commit: bacd148 phase2: record checkpoint after presign get negative test
- Working tree expected state: clean

## 2. Current CSRF State

| endpoint | function | method | csrf_exempt? | state-changing? | current JS sends token? |
|---|---|---|---:|---:|---:|
| /api/uploads/presign-put/ | presign_put() | POST | Yes | Yes | Yes |
| /api/uploads/commit/ | commit() | POST | Yes | Yes | Yes |
| /api/uploads/delete/<uuid>/ | delete_attachment() | DELETE | Yes | Yes | Yes |
| /api/uploads/presign-get/<uuid>/ | presign_get() | GET | No | No | token may be sent but is not required |

- `presign_put()` issues S3 PUT authorization.
- `commit()` writes Attachment metadata and can create event attachment links.
- `delete_attachment()` soft-deletes attachments.
- `presign_get()` is read-only and is not the CSRF restoration target.

## 3. Current Frontend Token Flow

- `upload-utils.js` sends `X-CSRFToken` for presign-put and commit.
- `upload-utils.js` `deleteAttachment()` sends `X-CSRFToken`.
- `process-events-ui.js` uses `uploadSingleFile()` through `uploadToEvent()`, not direct upload fetch.
- The contract detail event modal provides the token through `data-csrf` or `data-csrf-token`.
- Employee photo upload passes the token into `uploadImageWithThumbnail()` and `uploadSingleFile()`.
- The topbar avatar uses `presign_get()` GET only and is not affected.

The shared base template does not itself provide a hidden CSRF input. Current upload pages rely on page-level `{% csrf_token %}`, `{{ csrf_token }}`, or a `data-csrf` attribute.

## 4. Django CSRF Settings

Code-visible settings:

- `CsrfViewMiddleware` is active.
- `CSRF_TRUSTED_ORIGINS` is environment-based.
- `CSRF_COOKIE_SECURE` is environment-based and defaults to `True` in code.
- `SESSION_COOKIE_SECURE` is environment-based and defaults to `True` in code.
- `CSRF_COOKIE_HTTPONLY` is not explicitly set.
- SameSite settings appear to use Django defaults unless overridden elsewhere.

The `.env` file was not read or printed, so runtime overrides are not confirmed here.

Local risk:

- If `CSRF_COOKIE_SECURE=True` on local HTTP, browser cookie behavior may differ.
- Previous smoke tests do not prove CSRF cookie validity because write endpoints were `csrf_exempt`.

## 5. Risk If csrf_exempt Is Removed Immediately

### Employee photo upload

Employee photo upload sends a token, but the token and cookie pair must both be valid. A local Secure-cookie mismatch could produce CSRF 403.

### Employee photo_thumb upload

The original and thumbnail use separate presign-put and commit requests. Every request must pass CSRF validation.

### Event attachment upload

The event flow supplies the token through the contract page and shared upload helper. If presign-put succeeds but commit fails CSRF validation, an orphan S3 object may remain.

### Contract detail event modal upload

The modal supplies `data-csrf`, but its browser cookie and origin behavior still require smoke testing.

### Delete attachment

Both shared `deleteAttachment()` and the employee detail direct DELETE fetch send the token. Delete has a larger regression impact and should be restored in a separate slice.

### Excel attachment download

Excel download uses the read-only `presign_get()` GET flow. It is not a CSRF target and must remain download-only.

### PDF inline preview

PDF inline preview also uses `presign_get()` GET. It is not a CSRF target and its inline behavior must remain unchanged.

## 6. Strategy Options

### A. Remove csrf_exempt from all upload write endpoints at once

Advantage:

- closes all current upload CSRF exemptions together

Risk:

- mixes upload and delete regressions
- makes failures harder to isolate

Decision:

- not recommended

### B. Remove csrf_exempt from presign_put and commit first, delete later

Advantages:

- starts with endpoints already called through a shared token-sending helper
- limits the first code change to `views_uploads.py`
- keeps delete regression testing separate

Risks:

- commit CSRF failure after successful S3 PUT may leave an orphan object
- employee photo and thumbnail require multiple successful requests

Decision:

- recommended

### C. Keep csrf_exempt and add a custom CSRF enforcement helper

Risk:

- creates non-standard CSRF behavior alongside Django middleware
- increases the chance of an incomplete or inconsistent validation path

Decision:

- not recommended

### D. Defer implementation

Advantage:

- avoids immediate regression

Risk:

- state-changing upload endpoints remain exempt

Decision:

- not recommended long term

## 7. Recommended First Implementation Slice

Recommended first slice:

- modify `geoflow_ops/views_uploads.py` only
- remove `@csrf_exempt` from `presign_put()`
- remove `@csrf_exempt` from `commit()`
- leave `delete_attachment()` unchanged for now
- leave `presign_get()` unchanged
- no JS changes first
- no template changes first
- no DB change
- no migration
- do not touch Excel download-only
- do not touch PDF inline
- do not touch `presign_get()` READ authorization

## 8. Pre-implementation Checks

Before the code change or during smoke testing, verify without printing token values:

- employee detail provides a non-empty CSRF token source
- contract detail event modal provides a non-empty CSRF token source
- `upload-utils.js` sends `X-CSRFToken` for presign-put and commit
- missing-token requests fail with CSRF 403
- valid-token browser upload passes

Do not print actual token values.

## 9. Required Smoke Tests

Required after implementation:

- employee photo upload
- employee photo_thumb upload
- event attachment presign-put
- event attachment commit
- event attachment delete still works as before
- missing-token presign-put returns CSRF 403
- missing-token commit returns CSRF 403
- event PDF inline GET
- event Excel download GET
- normal employee detail
- damaged-RRN employee detail
- normal contract detail
- `presign_get()` READ authorization tests still pass
- `excel_preview.html` remains absent
- `thumbnail-utils.js` remains absent

## 10. Final Recommendation

Final recommendation:

- implement a limited slice now after documenting this design
- remove `csrf_exempt` from `presign_put()` and `commit()` only
- keep `delete_attachment()` `csrf_exempt` for a later slice
- do not implement custom CSRF logic
- do not modify JS/templates unless smoke testing proves token flow is broken
- do not implement delete authorization in this CSRF slice

