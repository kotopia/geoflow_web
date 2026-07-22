# Restricted-user Negative Authorization Test Plan

## 1. Current Baseline

- Branch: phase2-clean-base
- Baseline commit: 4b02a8f phase2: record checkpoint after presign get read authorization
- Working tree expected state: clean

## 2. Purpose

Plan negative authorization tests for `presign_get()` READ authorization.

Goal:

- verify that unauthorized users receive HTTP 403
- verify that no presigned URL is generated for denied requests
- avoid DB changes
- avoid S3 calls
- avoid printing sensitive data

## 3. Current Authorization Logic

`_request_has_any_perm()` checks:

- `request._gf_perms_cache`
- `request.session["gf_perms"]`
- `request.session["perms"]`

`_authorize_attachment_read()` allows:

- employee attachment with `directory.view`
- contract attachment with `contracts.view`
- employee-scoped event with `directory.view`
- contract-scoped event with `contracts.view`

Orgunit, project, and unknown entity or scope types fail closed.

Authorization failure happens before `generate_presigned_get_url()`.

## 4. Negative Test Cases

| case | user permissions | target attachment | expected result |
|---|---|---|---|
| employee denied | no `directory.view` | employee attachment | HTTP 403, no presigned URL |
| contract denied | no `contracts.view` | contract attachment | HTTP 403, no presigned URL |
| contract-event denied | no `contracts.view` | contract-scoped event attachment | HTTP 403, no presigned URL |
| employee-event denied | no `directory.view` | employee-scoped event attachment | HTTP 403, no presigned URL |
| orgunit fail closed | any permissions | orgunit attachment | HTTP 403 or fail closed |
| orgunit-event fail closed | any permissions | orgunit-scoped event attachment | HTTP 403 or fail closed |
| project unsupported | any permissions | project attachment | 404 or 403, no presigned URL |
| unknown unsupported | any permissions | unknown entity attachment | 404 or 403, no presigned URL |

## 5. Required Positive Controls

| case | user permissions | target attachment | expected result |
|---|---|---|---|
| employee allowed | `directory.view` | employee attachment | authorization passes |
| contract allowed | `contracts.view` | contract attachment | authorization passes |
| contract-event allowed | `contracts.view` | contract-scoped event attachment | authorization passes |

## 6. Recommended Test Method

Recommended method:

- RequestFactory/mock based test
- no real DB mutation
- no test user creation
- no permission DB update
- no S3 call
- mock `generate_presigned_get_url()`
- assert it is not called on denied requests

This method is safer than creating a temporary DB user because it does not add central user, role, or permission records and does not require later cleanup.

It is safer than modifying permission rows because it cannot affect a real tenant user's authorization state.

It is safer than manipulating the current browser session because it does not risk corrupting or misrepresenting the active authenticated session.

It is safer than using real attachment IDs in logs because synthetic objects and case labels can be used without exposing production-like identifiers or metadata.

## 7. Test Account Options

### A. Existing restricted user browser test

- Useful for a later integration test with real middleware and session loading.
- Use only if a restricted user already exists and its permission state is clearly understood.
- Do not create or alter the account during this slice.

### B. Temporary DB test user

- Can provide a controlled permission combination.
- Requires DB user, role, or permission mutations and cleanup.
- Deferred.

### C. RequestFactory/mock test

- Provides deterministic session permission combinations.
- Can isolate Attachment lookup, entity resolution, event scope, and S3 URL generation.
- Does not require real attachment IDs or DB permission updates.
- Recommended first.

### D. Current session manual manipulation

- May not reflect middleware-loaded permissions correctly.
- Can corrupt or confuse the active browser session.
- May require server-side session-store changes.
- Not recommended.

Recommendation:

- C first
- A only if a restricted user already exists and is clearly understood
- B deferred
- D not recommended

## 8. Sensitive Data Rules

Do not log or print:

- `.env`
- `RRN_SYM_KEY`
- `rrn_cipher`
- decrypted personal data
- presigned URL
- full object key if avoidable
- real employee name
- real employee email
- real contract name
- real attachment filename
- file content
- AWS credentials or URL signature

Allowed output format example:

- `case=employee_without_directory_view status=403 s3_called=false`

## 9. Recommended Next Implementation Slice

Next implementation, if approved:

- add test file only
- no production code changes
- target `presign_get()` negative authorization
- mock S3 URL generation
- mock or isolate entity resolution where possible
- verify denied requests return 403 before URL generation

Do not modify:

- `views_uploads.py`
- `delete_attachment()`
- DB
- migrations
- settings
- templates

## 10. Final Recommendation

Final recommendation:

- document this plan first
- then add a DB/S3-free RequestFactory/mock negative test file
- do not create or modify DB users yet
- do not implement delete authorization yet
- keep `delete_attachment()` authorization deferred until contract write/delete permission is confirmed

