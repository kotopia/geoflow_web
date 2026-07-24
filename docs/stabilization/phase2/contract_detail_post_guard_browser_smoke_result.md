# Contract Detail POST Guard Browser Smoke Result

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 3a21fcd phase2: guard contract detail post with edit permission
- Purpose: verify that contract detail POST/update passes after `contracts.edit` provisioning and session refresh/login

## 2. Smoke Scope

Approved scope:

- login/session refresh
- tenant entry
- contract list GET
- contract detail GET
- contract detail edit GET
- contract detail POST with no intended data change or minimal safe save
- post-save contract detail GET
- event list refresh

Not in scope:

- delete endpoint
- S3 mutation
- migration
- schema change
- permission provisioning
- role assignment change
- new code hardening

## 3. Sanitized Browser Result

| step | result |
|---|---|
| tenant entry | 200 |
| contract list GET | 200 |
| contract detail GET | 200 |
| contract detail edit GET | 200 |
| contract detail POST | 302 |
| post-save contract detail GET | 200 |
| contract-scoped event list GET | 200 |

No UUIDs, object keys, filenames, presigned URLs, attachment identifiers, event identifiers, user emails, or names are included.

## 4. Guard Validation

- `POST /contracts/<contract>/` reached `contract_detail_page()`.
- The request did not return HTTP 403.
- The view logged contract detail POST handling.
- The contract save path completed.
- The response redirected successfully with HTTP 302.
- The detail page loaded successfully after redirect.
- This confirms that `contracts.edit` provisioning and login/session refresh allowed the POST guard to pass for the tested tenant user.

## 5. Related Out-of-Scope Finding

- A separate multi-tenant login issue was observed for a user with multiple tenant candidates.
- The login flow attempted to redirect to `group_search`.
- The URL name was missing, causing `NoReverseMatch`.
- This is not part of the contract POST guard implementation.
- Recommended future separate document: `multi_tenant_group_search_login_route_analysis.md`.

No user email, tenant alias, UUID, or raw candidate data is included.

## 6. Safety Notes

Confirmed:

- no code was modified by this documentation task
- no migration was performed
- no schema change was performed
- no delete endpoint was called
- no S3 mutation was performed
- no `.env` contents were printed
- no `RRN_SYM_KEY` was printed or changed
- no ciphertext was printed
- no decrypted personal data was printed
- no UUID, object key, attachment filename, or raw ID was recorded
- no user email, name, or phone number was recorded
- `excel_preview.html` was not recreated
- `thumbnail-utils.js` was not created
