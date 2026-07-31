# Selected Tenant DB Credential Correction Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 537068f phase3: diagnose tenant db credential failure
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Background

- Post-repair metadata verification passed.
- Selectable candidates after metadata repair: 8.
- Incomplete connection metadata after repair: 0.
- Read-only manual smoke passed login, group selection, tenant routing, and tenant home loading.
- Contracts list loading failed with sanitized category: tenant database operational connection failure.
- Targeted diagnostic selected one tenant candidate locally.
- The selected target had complete central metadata.
- Tenant DB connection attempt failed with sanitized category: credential_invalid.
- Network was reachable.
- Timeout was not observed.
- Repair is needed.

## 3. Purpose

- Define a safe correction plan for the selected tenant DB credential failure.
- The future correction should update only DB user/password for the selected target.
- The future correction must not modify alias, database name, host, port, group status, or membership status.
- This document does not approve or perform DB write.
- This document does not perform DB SELECT or tenant DB connection test.

## 4. Current Diagnostic Summary

| check | result |
|---|---|
| target_count | 1 |
| metadata_complete | yes |
| connection_attempt_result | fail |
| sanitized_failure_category | credential_invalid |
| credential_rejected | yes |
| network_reachable | yes |
| timeout_observed | no |
| repair_needed | yes |

## 5. Future Correction Scope

Allowed future correction after separate explicit approval:

- Re-select the same failed target through a local-only numbered list.
- Accept DB user/password through local secure input only.
- Update only DB user/password fields for the selected one target.
- Use a transaction.
- Verify by tenant DB read-only connection test.
- Run `SELECT 1` only if connection succeeds.
- Document only sanitized counts and pass/fail results.

Not allowed:

- Editing alias.
- Editing database name.
- Editing host.
- Editing port.
- Activating inactive membership rows.
- Activating groups.
- Running migration.
- Running tenant provisioning.
- Browser smoke in the same correction step.
- Endpoint smoke in the same correction step.
- Recording credentials or raw identifiers.

## 6. Future Local Input Rule

- DB user/password must not be pasted into GPT.
- DB user/password must not be written into documents.
- DB user/password must not be printed in console output.
- DB user/password must not be committed to Git.
- DB user/password must be entered only in the local terminal or local secure prompt.
- If the correct credential values are uncertain, defer correction.

## 7. Future Execution Preconditions

Before future DB write:

- User must explicitly approve credential correction for the selected one target.
- Working tree must be clean.
- Forbidden files must be absent.
- Target must be selected locally and uniquely.
- Central metadata must still be complete.
- Failure category must still be credential_invalid or the correction must stop.
- Input values must be non-empty.
- The update must be limited to one selected target.
- No raw values or raw identifiers may be printed.

## 8. Future Verification Requirements

Allowed output after future correction:

| check | allowed output |
|---|---|
| selected_target_count | count |
| rows_updated | count |
| transaction_committed | 1_or_0 |
| transaction_rolled_back | 1_or_0 |
| tenant_connection_after_update | pass/fail |
| select_1_after_update | pass/fail/not_tested |
| credential_rejected_after_update | yes/no/unknown |
| repair_success | 1_or_0 |

Prohibited output:

- real DB host
- real DB name
- real DB user
- real DB password
- real tenant alias
- connection alias
- group name
- group UUID
- user email
- session value
- connection string
- raw exception message
- raw traceback
- local-only label
- raw identifier

## 9. Decision Rules

- If tenant connection succeeds after correction, prepare a separate read-only manual smoke retry plan.
- If credential is still rejected, verify the credential source outside GPT.
- If network failure appears instead, stop and prepare an infrastructure diagnostic plan.
- If database name or permission failure appears, stop and prepare a separate metadata or permission analysis plan.
- Do not combine correction and browser smoke in one step.

## 10. Out of Scope

- DB SELECT in this planning step.
- DB write in this planning step.
- Tenant DB connection test in this planning step.
- Browser smoke in this planning step.
- Endpoint smoke in this planning step.
- Migration.
- Tenant provisioning.
- S3 or presigned URL work.
- Inactive membership activation.
- Group activation.
- W342 warning cleanup.
- Broad template cleanup.

## 11. Safety Notes

- No code was modified.
- No test was modified.
- No database SELECT was performed.
- No tenant DB connection test was performed.
- No database write was performed.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated.
- No secrets were recorded.
- No local-only labels were recorded.
- No raw identifiers were recorded.
- `.env` contents were not printed.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 12. Conclusion

- The selected tenant DB failure is classified as credential_invalid.
- A future correction should update only DB user/password for the selected one target.
- Actual correction requires separate explicit DB write approval.
- No repair is performed in this planning step.
