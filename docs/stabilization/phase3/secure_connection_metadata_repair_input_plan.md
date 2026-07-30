# Secure Connection Metadata Repair Input Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: c2ca812 phase3: document incomplete connection metadata missing fields
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define a safe local-only input process for repairing incomplete connection metadata.
- The previous review found 2 incomplete rows.
- Both rows are missing database user and database password fields.
- Alias, database name, host, and port were not missing.
- This document does not approve or perform repair.
- This document does not perform database read or write.

## 3. Problem Summary

| item | count |
|---|---:|
| incomplete connection metadata rows | 2 |
| missing database user | 2 |
| missing database password | 2 |
| missing alias | 0 |
| missing database name | 0 |
| missing host | 0 |
| missing port | 0 |
| alias consistency pass | 2 |
| repair requires secret input | 2 |

## 4. Security Rule

- Database user and password must not be pasted into GPT.
- Database user and password must not be written into documentation.
- Database user and password must not be printed in console output.
- Database user and password must not be committed to Git.
- Database user and password must not be exposed in raw tracebacks.
- `.env` contents must not be printed.
- Raw identifiers must not be recorded.

## 5. Approved Future Input Methods

### Method A: Local environment variables

- The user sets repair values in local environment variables.
- The future repair command reads the values locally.
- The values are never printed.
- The values are never written to a document.

Example variable names only:

- `GF_REPAIR_DB_USER_ROW_1`
- `GF_REPAIR_DB_PASSWORD_ROW_1`
- `GF_REPAIR_DB_USER_ROW_2`
- `GF_REPAIR_DB_PASSWORD_ROW_2`

Do not include real values in this document.

### Method B: Local secure prompt

- The future repair script asks for values in the local terminal.
- Password input must be hidden or not echoed when possible.
- The script must not print the entered values.
- The script must only print sanitized success/failure counts.

### Method C: Defer repair

- Use this method if the correct user/password values are unknown.
- Use this method if the tenant is no longer needed.
- Use this method if the secure source of truth is unclear.
- No database change is performed.

## 6. Future Repair Preconditions

Before any database write:

- User must explicitly approve the repair step.
- The exact 2 target rows must be selected internally without printing raw identifiers.
- Missing field categories must be confirmed again with SELECT.
- The source of the database user/password values must be approved.
- A narrow repair script must be prepared and reviewed.
- The repair script must update only the missing user/password fields for the approved target rows.
- No inactive membership row may be activated.
- No group may be activated.
- No migration may be run.

## 7. Future Repair Script Requirements

A future repair script must:

- Use a transaction.
- Update only the approved 2 incomplete metadata rows.
- Update only database user and password fields.
- Avoid printing raw values.
- Avoid printing raw identifiers.
- Avoid printing connection strings.
- Avoid printing exception details that may include host or credentials.
- Report only sanitized counts and boolean results.
- Stop if target row count is not exactly 2.
- Stop if unexpected missing fields are detected.
- Stop if input values are empty.
- Stop if alias consistency fails.
- Verify after update with a sanitized SELECT.
- Roll back on error.

## 8. Future Verification Output

Allowed future output:

| check | allowed output |
|---|---|
| target_rows_found | count |
| rows_updated | count |
| user_field_present_after_update | count |
| password_field_present_after_update | count |
| alias_consistency_pass | count |
| repair_success | yes/no |
| selectable_candidate_count_after_repair | count |

Prohibited future output:

- real database user
- real database password
- real database host
- real database name
- real tenant alias
- connection alias
- group name
- group UUID
- user email
- user ID
- session value
- connection string
- raw exception message
- raw identifier

## 9. Recommended Future Sequence

1. Commit this input plan.
2. Prepare a separate DB repair script plan.
3. Get explicit approval for DB write.
4. Run a final read-only precheck.
5. Enter repair values locally using approved secure input method.
6. Execute the narrow repair transaction.
7. Run sanitized verification SELECT.
8. Document the result.
9. Do not activate inactive memberships or groups in the same step.

## 10. Out of Scope

- DB SELECT in this planning step.
- DB write in this planning step.
- Secret input in this planning step.
- Repair script implementation in this planning step.
- Inactive membership activation.
- Group activation.
- Migration.
- Endpoint smoke.
- Browser smoke.
- S3 or presigned URL work.
- Broad template cleanup.
- W342 warning cleanup.

## 11. Safety Notes

- No code was modified.
- No test was modified.
- No database SELECT was performed.
- No database write was performed.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated.
- No secrets were recorded.
- No raw identifiers were recorded.
- `.env` contents were not printed.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 12. Conclusion

- The 2 incomplete metadata rows require database user and password input.
- Those values must be supplied only through a local secure process.
- This plan does not approve repair.
- A future DB write requires separate explicit approval.
