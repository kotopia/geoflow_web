# Group Selection Selectable Candidate Filtering Browser Smoke Result

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 9abfe2d phase2: document selectable tenant candidate filtering
- Working tree expected state: clean

## 2. Smoke Setup

- Existing runserver processes were checked.
- A fresh `--noreload` development server was started from the clean worktree.
- The browser flow started from `/login/`.
- No code changes were made during the smoke.
- No migration was run.

## 3. Observed Result

- Multi-membership login was tested.
- Login completed successfully.
- The group-selection page was not shown.
- The user was routed directly to the tenant home or main page.
- The tenant home or main page returned HTTP 200.
- The contracts page returned HTTP 200.
- `ConnectionDoesNotExist` was not observed.
- `ImproperlyConfigured` was not observed.
- Server logs showed tenant route resolution and post-login tenant routing.
- Direct tenant routing occurred because selectable-candidate filtering left only one connectable candidate under the existing login flow.
- No successful test is claimed for showing a group-selection page with multiple selectable candidates.
- Single-tenant smoke was not fully completed in this result unless separately confirmed.

No actual user, group, tenant, connection, database, or raw identifier is recorded.

## 4. Interpretation

- The previous tenant connection failure is functionally resolved for the tested selectable tenant candidate.
- The contracts workflow reached HTTP 200 after filtering.
- Non-selectable candidates are no longer offered into the failing tenant-connection path.
- The group-selection page was skipped because only one selectable candidate remained.
- This is consistent with the existing login flow.
- Whether multi-membership users should still see a selection or notice page when only one selectable candidate remains is a separate UX policy decision.

## 5. Result Table

| check | result |
|---|---|
| fresh `--noreload` runserver | completed |
| clean HEAD confirmed | yes |
| `/login/` start | yes |
| multi-membership login | completed |
| group selection page | skipped |
| tenant home/main | HTTP 200 |
| contracts page | HTTP 200 |
| `ConnectionDoesNotExist` | not observed |
| `ImproperlyConfigured` | not observed |
| non-selectable candidate failure path | not reached |
| single-tenant smoke | not confirmed in this result |
| successful browser smoke claimed | yes, for filtered selectable candidate tenant workflow |

## 6. Follow-up Decision

### Option A: Keep Current Behavior

- If filtering leaves one selectable candidate, route directly to the tenant.
- This is the simplest option and is currently working.

### Option B: Change UX Policy

- If raw memberships are multiple but only one selectable candidate remains, still show a group-selection or notice page.
- The page should show only selectable candidates.
- Non-selectable groups must not be selectable.
- Any message must be generic and sanitized.

Recommended next step:

- Commit this smoke result first.
- Then decide whether to keep the current auto-routing behavior or design a separate multi-membership UX notice page.

## 7. Not Performed

- No code change
- No DB write
- No migration
- No schema change
- No tenant provisioning
- No permission provisioning
- No S3 access
- No presigned URL generation
- No event, upload, or delete workflow
- No template or static change

## 8. Safety Notes

- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext or decrypted personal data was printed.
- No actual user email, group name, group UUID, tenant alias, connection alias, DB host, DB password, DB configuration value, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
