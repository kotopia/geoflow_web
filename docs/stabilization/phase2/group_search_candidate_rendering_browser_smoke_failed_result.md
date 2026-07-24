# Multi-tenant group_search Candidate Rendering Browser Smoke Failed Result

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 8be2081 phase2: document group search candidate rendering implementation

## 2. Observed Result

- The local Django server started.
- Multi-tenant login reached the group selection page.
- The initial `group_search` `NoReverseMatch` was not observed.
- The group selection page rendered after the candidate rendering fix.
- An authorized displayed candidate was selected.
- Post-selection tenant flow was attempted.
- The tenant home or tenant workflow page was not reached successfully.
- A Django `ConnectionDoesNotExist` error occurred because the selected tenant database alias was not registered in the active Django connections.
- Single-tenant confirmation was not completed in this smoke.

No actual user email, group identifier, group name, tenant alias, tenant alias candidate list, UUID, raw identifier, identifying URL, or literal connection alias from the error page is recorded.

## 3. Interpretation

- The original unqualified `group_search` reverse issue appears resolved.
- The previous selectable-but-forbidden group problem appears to have progressed past the group selection step.
- The remaining failure now occurs during tenant database connection resolution after group selection.
- The selected tenant alias was stored or resolved, but Django did not have a matching connection configured at request time.
- This is likely a tenant database connection registration or loading issue rather than a group search URL issue.
- Group selection authorization must not be weakened to address this failure.
- This must not be treated as a migration issue without further analysis.

## 4. Sanitized Result Table

| step | result |
|---|---|
| local server start | completed |
| multi-tenant login | completed |
| group selection page | reached |
| group_search NoReverseMatch | not observed |
| authorized candidate selection | completed |
| post-selection tenant routing | attempted |
| tenant home or workflow page | failed |
| observed exception category | ConnectionDoesNotExist |
| single-tenant confirmation | not completed |

## 5. Follow-up Fix Direction

- Analyze how tenant database aliases are registered for runtime connections.
- Compare the working single-tenant alias flow with the selected multi-tenant alias flow.
- Verify whether selected candidate data contains a database alias that must be dynamically registered before tenant routing.
- Verify whether central `group_db_config` data is loaded into `connections.databases`.
- Ensure that `/after-login/` can prepare the selected tenant alias before routing to tenant pages.
- Keep group selection candidate validation intact.

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
- No tenant alias was recorded.
- No tenant alias candidate list was recorded.
- No UUID or raw identifier was recorded.
- No literal connection alias from the error page was recorded.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
