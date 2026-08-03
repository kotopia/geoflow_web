# Selected Tenant DB User Metadata Correction Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 3b0a1bb phase3: document selected tenant metadata mismatch
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define a narrow correction plan for the selected tenant connection metadata.
- Correct only the mismatched PostgreSQL database user field.
- Preserve all connection fields that matched the local read-only comparison.
- Defer password assessment until a separately approved step.

## 3. Confirmed Preconditions

| check | confirmed result |
|---|---|
| selected target rows | 1 |
| host | matched |
| port | matched |
| database name | matched |
| database user | mismatched |
| password | not assessed |
| runtime source | dynamic `group_db_config` |

- The selected target uses dynamic central metadata for runtime connection preparation.
- The `db_user` field is mapped to the Django connection `USER` setting.
- The value must be a PostgreSQL connection role name.
- It must not be an application login user, application user identifier, or email address.

## 4. Approved Future Correction Scope

The future correction candidate is exactly one selected central metadata row and exactly one field:

| item | treatment |
|---|---|
| selected target count | exactly 1 |
| `db_user` | eligible for correction after explicit approval |
| host | unchanged |
| port | unchanged |
| database name | unchanged |
| password | unchanged and not assessed |
| alias and group relationship | unchanged |

The execution step must stop without a write if the target count is not exactly one or if any precondition has changed.

## 5. Local Input Requirements

- Obtain the PostgreSQL connection role locally from an authoritative database administration source.
- Do not paste the role name into GPT, documentation, logs, command history, or source files.
- Use a hidden or otherwise local-only prompt during the separately approved execution step.
- Confirm locally that the input is a PostgreSQL role and not the web login account.
- Do not request or enter a password in the database-user-only correction step.

## 6. Proposed Future Execution Sequence

1. Start from a clean working tree and the approved baseline.
2. Perform a central database SELECT to re-identify the selected target without printing identifiers.
3. Confirm that exactly one row is targeted.
4. Reconfirm that host, port, and database name remain unchanged and that only `db_user` is the approved mismatch.
5. Read the corrected PostgreSQL role through a local-only prompt.
6. Begin an explicit central database transaction.
7. Update only the selected row's `db_user` field.
8. Verify that exactly one row was updated and that no other field changed.
9. If a tenant connection verification is separately approved, perform it before commit.
10. Commit only after every approved verification passes; otherwise roll back.
11. Report sanitized counts and pass/fail categories only.

This document does not approve or execute any database write or tenant connection test.

## 7. Fail-closed Conditions

The future correction must roll back or stop before writing if any of the following occurs:

- Target count is zero or greater than one.
- The selected target cannot be re-identified safely.
- The supplied value is empty.
- The supplied value is identified as an application login account rather than a PostgreSQL role.
- Host, port, database name, alias consistency, membership state, or group state has changed unexpectedly.
- Any field other than `db_user` would be modified.
- Verification scope or authorization is unclear.
- A raw identifier, secret, or connection value would be exposed.

## 8. Verification Plan

- Verify the transaction affected exactly one central metadata row.
- Verify only `db_user` changed.
- Verify host, port, database name, password, alias, and relationship fields remained unchanged.
- Record only sanitized counts and boolean results.
- A tenant database connection test requires separate explicit approval.
- Password validity must not be inferred from a database-user-only correction result.

## 9. Out of Scope

- Database write in this planning task
- Tenant database connection test
- Password input, comparison, or correction
- Host correction
- Port correction
- Database name correction
- Alias correction
- Membership or group activation
- Code or test change
- Migration or schema change
- Endpoint or browser execution
- S3 or presigned URL work
- Git add, commit, or push

## 10. Safety Notes

- No database write was performed.
- No tenant database connection was attempted.
- No password was requested or entered.
- No host, port, database name, password, or alias was changed.
- No code or test was modified.
- No migration was performed.
- No endpoint was called.
- No browser was executed.
- No S3 access or presigned URL work was performed.
- No sensitive value or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 11. Conclusion

- Host, port, and database name are confirmed matches.
- The selected target's `db_user` is the only confirmed metadata mismatch.
- The next correction candidate is the `db_user` field of exactly one selected row.
- The correction value must be the PostgreSQL connection role, not a web login user.
- Password assessment and all other metadata changes remain deferred.
- Any correction execution requires separate explicit approval.
