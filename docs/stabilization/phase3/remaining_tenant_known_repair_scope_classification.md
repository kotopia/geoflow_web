# Remaining Tenant Known Repair Scope Classification

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 5ab8bc9 phase3: inventory remaining tenant repair states
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Apply user-confirmed business knowledge to the remaining sanitized tenant targets.
- Separate the host-only metadata candidate from the credential-and-migration candidate.
- Exclude unrelated targets from the current repair scope.
- Define strict field boundaries before any future database write or migration.

## 3. Scope

- Selectable central metadata was read only to display a local-only target list.
- Candidate mapping was performed by the user using sanitized target numbers.
- No tenant connection was attempted.
- No database write was performed.
- No host, user, or password was modified.
- No migration or schema operation was performed.
- No code, endpoint, browser, or S3 operation was performed.
- No actual tenant label or connection value was recorded.

## 4. User-confirmed Repair Knowledge

- Exactly one remaining tenant needs a host-only central metadata correction.
- The host-only candidate's existing PostgreSQL user and password are correct.
- Exactly one remaining tenant needs PostgreSQL credential correction and may also need the attachment migration.
- Attachment migration must not be considered until credential correction and connection validation succeed.
- One remaining tenant is outside the current known repair scope.

## 5. Sanitized Target Classification

| sanitized target | classification | current treatment |
|---|---|---|
| target 2 | host_only_repair_candidate | eligible for a separate host-only correction plan |
| target 4 | credential_and_migration_candidate | credential correction first; migration decision only after successful connection and read-only inventory |
| target 1 | excluded_from_current_repair | no repair action in the current scope |

## 6. Classification Counts

| classification | count |
|---|---:|
| host_only_repair_candidate | 1 |
| credential_and_migration_candidate | 1 |
| excluded_from_current_repair | 1 |

## 7. Target 2 Field Boundary

- Target 2 is the host-only repair candidate.
- Only the central metadata host field may become a future correction candidate.
- PostgreSQL database user must not change.
- PostgreSQL database password must not change.
- Port must not change.
- Database name must not change.
- Alias and group relationship must not change.
- A future correction requires local-only host input, an exact-one-row transaction, connection validation, read-only `SELECT 1`, and rollback on failure.
- This classification does not authorize the correction execution.

## 8. Target 4 Field and Sequence Boundary

- Target 4 is the credential-and-migration candidate.
- Host must not change.
- Port must not change.
- Database name must not change.
- Alias and group relationship must not change.
- PostgreSQL user and password must be treated as one credential pair from the same authoritative local source.
- Credential repair must occur before any migration decision.
- After credential correction, tenant connection and read-only `SELECT 1` must pass.
- Migration history and attachment table presence must then be inspected read-only.
- Attachment migration may be planned only if the connection passes and the schema evidence confirms it is needed.
- This classification does not authorize credential correction or migration execution.

## 9. Target 1 Exclusion

- Target 1 is excluded from the current repair scope.
- No host, credential, migration, or schema repair is planned for target 1 in this workstream.
- The prior `unclear_stop` classification remains protective.
- Target 1 may be reviewed only through a separately approved task with new evidence.
- No conclusion about its credentials or schema should be inferred from its exclusion.

## 10. Required Repair Order

The two repair candidates must remain independent:

1. Prepare a target 2 host-only correction plan.
2. If separately approved, correct only target 2 host and validate read-only connection behavior.
3. Prepare a target 4 credential-pair correction plan.
4. If separately approved, correct only target 4 PostgreSQL user and password and validate read-only connection behavior.
5. Only after target 4 connection success, perform a read-only attachment migration and table inventory.
6. If migration is needed, require target-specific static review, precheck, backup, exact command review, execution approval, and postcheck.

Do not combine target 2 and target 4 in one transaction, script, or migration operation.

## 11. Fail-closed Rules

- Stop if a selected target count is not exactly one.
- Stop if target numbers cannot be mapped locally and unambiguously.
- Stop if target 2 would modify user, password, port, database name, alias, or group information.
- Stop if target 4 would modify host, port, database name, alias, or group information.
- Stop if target 4 migration is proposed before connection success and read-only schema inventory.
- Stop if target 1 is included in any correction command.
- Stop if a raw identifier, credential, connection value, or error would be exposed.
- Stop if repair scopes are combined or broadened without explicit approval.

## 12. Recommended Next Action

- Prepare a separate target 2 host-only metadata correction plan first.
- Preserve the existing target 2 PostgreSQL user and password.
- Keep target 4 unchanged until its credential-pair correction plan is separately reviewed.
- Keep target 1 excluded.
- Do not run any migration based solely on this classification.

## 13. Not Performed

- No database write
- No host, user, or password modification
- No tenant connection test
- No migration execution
- No table creation, alteration, rename, or deletion
- No code or test change
- No endpoint or browser execution
- No S3 or presigned URL operation
- No git add, commit, or push

## 14. Safety Notes

- No actual tenant name, alias, host, port, database name, database user, password, UUID, email, session value, or raw identifier was recorded.
- The document uses sanitized target numbers only.
- No raw error was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 15. Conclusion

- Target 2 is the host-only repair candidate.
- Target 4 is the credential-and-migration candidate.
- Target 1 is excluded from the current repair scope.
- Target 2 user and password must remain unchanged.
- Target 4 host must remain unchanged.
- Target 4 migration may be considered only after credential repair, connection success, and read-only schema confirmation.
- No repair or migration execution is authorized by this classification document.
