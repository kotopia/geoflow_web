# Group Selection Auto-route Policy Decision

## 1. Baseline

- Branch: `phase2-clean-base`
- Current HEAD: `8568324 phase2: checkpoint selectable tenant candidate stabilization`
- Working tree expected state: clean

## 2. Decision

The selected policy is Option A.

- If selectable tenant candidates are reduced to one candidate, the login flow routes directly to that tenant.
- If selectable tenant candidates are two or more, the group-selection page is shown.
- Non-selectable candidates are never stored in session `tenant_candidates`.
- Non-selectable candidates are never rendered as selectable choices.
- The group-selection page is not forced merely because raw membership count is greater than one.

## 3. Reason

- The current behavior is stable and already smoke-tested.
- The tested selectable tenant workflow reached the tenant home/main page with HTTP 200.
- The contracts page reached HTTP 200.
- `ConnectionDoesNotExist` was not observed.
- `ImproperlyConfigured` was not observed.
- For stabilization, avoiding unnecessary UX changes is safer.
- Showing incomplete or non-connectable groups would reintroduce the previous failure path.

## 4. Confirmed Current Policy

| condition | behavior |
|---|---|
| zero selectable candidates | central fallback flow |
| one selectable candidate | direct tenant route |
| two or more selectable candidates | group-selection page |
| non-selectable candidates | excluded from session and UI |

## 5. Deferred UX Option

The following is deferred and not implemented:

- showing a group-selection or notice page when raw memberships are multiple but selectable candidates are reduced to one
- showing generic unavailable-group notices
- showing disabled non-selectable group rows

Any future UX change must preserve:

- no non-selectable candidate can be selected
- no raw group ID, UUID, tenant alias, DB alias, DB host, password, or config value is exposed
- session-based `group_select` 403 validation remains
- tenant connection helper remains strict

## 6. Safety Notes

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
- No actual user email, group name, group UUID, tenant alias, connection alias, DB host, DB password, DB config value, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
