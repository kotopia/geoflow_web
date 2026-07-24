# Multi-tenant group_search Login Browser Smoke Failed Result

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 74bdf01 phase2: document group search login fix implementation

## 2. Observed Result

- The local Django server started.
- The `/login/` page loaded.
- Multi-tenant login reached the group selection flow.
- `NoReverseMatch` was not observed at the initial group search redirect.
- The group selection page displayed multiple selectable groups.
- Selecting one displayed group returned HTTP 403.
- The tenant home was not reached through the multi-tenant selection flow.
- The single-tenant flow was not completed in this smoke.

No user email, group UUID, tenant alias, group name, candidate list, raw identifier, or URL containing identifiers is recorded.

## 3. Interpretation

- The initial `control:group_search` routing fix appears to have removed the original `NoReverseMatch`.
- The HTTP 403 came from group selection validation.
- This is safe behavior if the selected group was not present in the tenant candidates stored in the session.
- However, the UI appears to display at least one central or non-candidate group that cannot be selected.
- The remaining issue is therefore likely candidate-list rendering or candidate-shape validation rather than the original URL reversing issue.

## 4. Follow-up Fix Direction

- Do not loosen the HTTP 403 validation.
- Do not accept arbitrary group identifiers from the page.
- Update the group selection page or its data source to show only the authorized tenant candidates stored in the session.
- If central group selection is required, design it as a separate central-dashboard flow.
- Verify that authorized tenant candidates can be selected without HTTP 403.

## 5. Sanitized Result Table

| step | result |
|---|---|
| local server start | completed |
| login page GET | 200 |
| multi-tenant login POST | completed |
| group_search NoReverseMatch | not observed |
| group selection page | reached |
| displayed group selection | 403 |
| tenant home after selection | not reached |
| single-tenant confirmation | not completed |

## 6. Not Performed

- No code was changed.
- No migration was performed.
- No schema change was made.
- No tenant database business-data write was performed.
- No S3 access was performed.
- No presigned URL work was performed.
- No event, upload, or delete workflow was exercised.
- No successful browser smoke result is claimed.

## 7. Safety Notes

- No user email was recorded.
- No group identifier was recorded.
- No tenant alias candidate list was recorded.
- No UUID or raw identifier was recorded.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
