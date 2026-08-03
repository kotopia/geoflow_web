# Selected Tenant DB User and Password Metadata Correction Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: f2b8b1b phase3: document selected tenant db user correction rollback
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define a narrowly scoped correction plan for the selected tenant connection metadata.
- Correct `db_user` and `db_password` together as one atomic operation.
- Preserve all confirmed matching connection fields and relationship metadata.
- Commit only after a read-only tenant connection and `SELECT 1` both pass.

## 3. Evidence

- The selected tenant host matched the locally known actual host.
- The selected tenant port matched the locally known actual port.
- The selected tenant database name matched the locally known actual database name.
- A `db_user` mismatch was confirmed.
- The user successfully completed a local `psql SELECT 1` using the actual PostgreSQL user and password.
- A prior `db_user`-only transaction tested the new user with the previously stored password.
- That connection validation failed and the transaction rolled back.
- No metadata change was committed by the failed attempt.
- The next correction candidate is therefore `db_user` plus `db_password`, and no other field.

## 4. Field Semantics

| metadata field | required meaning |
|---|---|
| `db_user` | The PostgreSQL connection role name used by the successful database client connection. It must not be a web login user, email, or application user identifier. |
| `db_password` | The password belonging to that exact PostgreSQL connection role. |

The two values form a credential pair and must be supplied together from the same locally verified connection source.

## 5. Exact Correction Scope

| item | future treatment |
|---|---|
| selected target rows | exactly 1 |
| `db_user` | update from local secure input |
| `db_password` | update from local secure input |
| host | unchanged |
| port | unchanged |
| database name | unchanged |
| alias | unchanged |
| group relationship | unchanged |
| all other metadata | unchanged |

The future execution must stop before writing if the selected target count is not exactly one.

## 6. Secure Local Input Requirements

- Obtain both values from the same locally verified PostgreSQL connection configuration.
- Use hidden local prompts for both values.
- Do not paste either value into GPT, documentation, logs, shell history, source code, or command arguments.
- Do not load or print environment contents.
- Confirm locally that the user value is the PostgreSQL role used by the successful `psql` test.
- Confirm locally that the password belongs to that exact role.

## 7. Proposed Future Execution Sequence

1. Confirm the approved baseline and clean working tree.
2. Display the selectable targets in a local-only numbered list.
3. Select the previously verified target without recording its label or identifier.
4. Re-identify the selected central metadata row and require an exact target count of one.
5. Reconfirm that host, port, and database name still match and are not correction candidates.
6. Read the PostgreSQL role and its password through separate hidden local prompts.
7. Begin an explicit transaction on the central database.
8. Lock the selected metadata row.
9. Update only `db_user` and `db_password`.
10. Verify within the transaction that exactly one row was updated.
11. Verify that host, port, database name, alias, group relationship, and all unrelated fields are unchanged.
12. Using the unchanged host, port, and database name plus the updated credential pair, open a tenant database connection for validation only.
13. Set the tenant validation connection to read-only mode.
14. Execute `SELECT 1` only.
15. Commit the central metadata transaction only if the connection and `SELECT 1` both pass.
16. Roll back the entire transaction if connection, query, target-count, or invariant validation fails.
17. Close all connections and report sanitized counts and categories only.

## 8. Commit Conditions

All of the following must be true before commit:

- Exactly one selected metadata row is locked and updated.
- Only `db_user` and `db_password` changed.
- Host, port, and database name remained unchanged.
- Alias and group relationship remained unchanged.
- The tenant connection using the updated credential pair succeeded.
- The tenant connection was placed in read-only mode.
- `SELECT 1` returned the expected result.
- No sensitive value or raw exception was printed.

## 9. Rollback Conditions

The future execution must roll back if any of the following occurs:

- Target count is not exactly one.
- Either credential input is empty.
- The user input is not confirmed as a PostgreSQL connection role.
- The password is not confirmed as belonging to that role.
- Any non-target field changes.
- Tenant connection validation fails.
- `SELECT 1` fails or returns an unexpected result.
- A write is attempted against the tenant database.
- The operation would expose a credential, identifier, or raw exception.
- Execution scope or approval becomes unclear.

## 10. Sanitized Execution Report Requirements

A future execution result should record only:

- selected target count
- credential fields requested as yes or no
- update row count
- non-target field update counts, expected to be zero
- transaction committed or rolled back
- tenant connection pass or fail
- `SELECT 1` pass, fail, or not tested
- sanitized failure category
- repair success as zero or one

No actual connection value or identifier may be recorded.

## 11. Out of Scope for This Planning Task

- Database write
- Tenant database connection test
- Password input
- Host, port, or database name modification
- Alias or group modification
- Code or test change
- Migration or schema change
- Endpoint or browser execution
- S3 or presigned URL work
- Git add, commit, or push

## 12. Safety Notes

- No database write was performed.
- No tenant database connection was attempted.
- No password was requested or entered.
- No metadata field was modified.
- No code or test was modified.
- No migration was performed.
- No endpoint was called.
- No browser was executed.
- No sensitive value or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 13. Conclusion

- The next correction candidate is exactly one selected row's `db_user` and `db_password` pair.
- `db_user` must be the PostgreSQL connection role.
- `db_password` must be the password for that exact role.
- Host, port, database name, alias, and group information must not change.
- The future execution must use a transaction, validate with a read-only tenant connection and `SELECT 1`, commit on complete success, and roll back on any failure.
- Execution requires separate explicit approval.
