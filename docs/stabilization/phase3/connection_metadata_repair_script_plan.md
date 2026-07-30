# Connection Metadata Repair Script Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: a5149ab phase3: plan secure connection metadata repair input
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define a future safe repair script design for 2 incomplete connection metadata rows.
- The missing fields are database user and database password.
- Alias, database name, host, and port are already present.
- This document does not implement the script.
- This document does not perform database read or write.
- This document does not approve repair execution.

## 3. Repair Target Summary

| item | count |
|---|---:|
| incomplete metadata rows | 2 |
| missing database user | 2 |
| missing database password | 2 |
| missing alias | 0 |
| missing database name | 0 |
| missing host | 0 |
| missing port | 0 |
| alias consistency pass | 2 |

## 4. Future Script Type

The future script should be a local-only one-time repair command.

It must:

- run only on the local operator machine
- read secret inputs locally
- avoid printing secret values
- avoid writing secret values to documents
- avoid committing secret values to Git
- use a database transaction
- stop unless exactly 2 target rows are found
- update only database user and database password fields
- verify the result with sanitized counts only

## 5. Target Row Selection Rule

The future script must select only rows that match all of these conditions:

- row belongs to the incomplete connection metadata category
- alias is present
- database name is present
- host is present
- port is present
- database user is missing
- database password is missing
- alias consistency passes
- row is not an inactive membership repair target
- target count is exactly 2

The script must stop if:

- target count is not exactly 2
- any unexpected missing field is found
- alias consistency fails
- any target overlaps with deferred inactive membership rows
- any input value is empty
- any database error occurs

## 6. Local-only Row Mapping

Before repair execution, the future script may display a local-only numbered list.

Allowed local-only display on the user's machine:

- row number
- business label for user decision support
- sanitized status fields

Prohibited in GPT report or documentation:

- real tenant alias
- connection alias
- database host
- database name
- database user
- database password
- group UUID
- group name
- user email
- user ID
- raw identifier

The user must report back only row numbers and decisions, not actual labels or identifiers.

## 7. Secret Input Design

Approved input methods:

### Method A: Local environment variables

Example variable names only:

- `GF_REPAIR_DB_USER_ROW_1`
- `GF_REPAIR_DB_PASSWORD_ROW_1`
- `GF_REPAIR_DB_USER_ROW_2`
- `GF_REPAIR_DB_PASSWORD_ROW_2`

The script must read these variables locally and must not print their values.

### Method B: Local secure prompt

The script may ask for values interactively.

Requirements:

- password input should be hidden or not echoed when possible
- entered values must not be printed
- entered values must not be logged
- only sanitized success/failure counts may be printed

## 8. Future Update Rule

The future repair transaction must update only:

- database user field
- database password field

The future repair transaction must not update:

- alias
- database name
- host
- port
- group status
- membership status
- tenant status
- user status
- any unrelated metadata field

## 9. Future Verification Rule

After update, the script must verify using sanitized SELECT only.

Allowed output:

| check | allowed output |
|---|---|
| target_rows_found_before_update | count |
| rows_updated | count |
| user_field_present_after_update | count |
| password_field_present_after_update | count |
| alias_consistency_pass_after_update | count |
| incomplete_rows_remaining | count |
| selectable_candidates_after_repair | count |
| repair_success | yes/no |

Prohibited output:

- actual database user
- actual database password
- actual database host
- actual database name
- actual tenant alias
- actual connection alias
- actual group name
- actual group UUID
- actual user email
- connection string
- raw exception message
- raw identifier

## 10. Rollback and Failure Rule

The future script must roll back if:

- target count is not exactly 2
- input values are missing
- update count is not exactly 2
- verification does not pass
- unexpected metadata fields are affected
- database error occurs

On failure, the script should report only sanitized failure reason categories.

## 11. Future Execution Sequence

1. Commit this script plan.
2. Prepare a temporary local repair script or management command plan.
3. Get explicit DB write approval.
4. Run final read-only precheck.
5. Display local-only row mapping.
6. Enter database user/password locally.
7. Execute repair in a transaction.
8. Run sanitized verification.
9. Document repair result.
10. Remove or avoid committing any temporary secret-bearing material.

## 12. Out of Scope

- Script implementation in this planning step.
- DB SELECT in this planning step.
- DB write in this planning step.
- Secret input in this planning step.
- Inactive membership activation.
- Group activation.
- Migration.
- Endpoint smoke.
- Browser smoke.
- S3 or presigned URL work.
- W342 warning cleanup.
- Broad template cleanup.

## 13. Safety Notes

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

## 14. Conclusion

- The future repair script must be narrow, transactional, and local-only.
- The script must update only database user and password for the approved 2 rows.
- Secret values must remain local and must never be pasted into GPT or committed.
- Actual DB repair requires separate explicit approval.
