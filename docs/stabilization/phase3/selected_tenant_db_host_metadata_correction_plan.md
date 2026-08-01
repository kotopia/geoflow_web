# Selected Tenant DB Host Metadata Correction Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 907fcc9 phase3: document selected tenant db password correction rollback
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Background

- The intended tenant target was re-identified previously.
- Password-only correction attempts were rolled back with sanitized category `credential_invalid`.
- The user then confirmed that the deployment expectation is one RDS server containing both central and tenant databases.
- The user also confirmed that the selected tenant metadata DB host points to a different RDS host than the actual pgAdmin server host.
- RDS endpoint suffix similarity does not mean the same RDS target.
- The primary suspected cause is now DB host metadata mismatch, not DB password invalidity.

## 3. Purpose

- Define a safe correction plan for selected tenant DB host metadata only.
- Future correction must update the DB host only for exactly 1 re-identified selected row.
- Port, database name, DB user, DB password, alias, group code, and group name must not be changed.
- Tenant DB schema, data, accounts, and permissions must not be changed.
- The correction must be verified by a read-only tenant DB connection and `SELECT 1` before commit.

## 4. Current Sanitized Finding

| check | result |
|---|---|
| deployment_expected_single_rds | yes |
| pgadmin_central_and_tenant_same_server | yes |
| selected_tenant_db_host_matches_actual_rds | no |
| rds_endpoint_suffix_similarity_is_sufficient | no |
| password_only_attempts_committed | 0 |
| current_primary_repair_candidate | db_host_metadata_only |

## 5. Future Correction Scope

Allowed after separate user approval:

- Central DB SELECT to locate selectable candidates.
- Local-only target number selection.
- Local-only confirmation that the selected target is the intended tenant target.
- Local-only input of the correct RDS host.
- Central DB UPDATE of the DB host only for exactly 1 selected `group_db_config` row.
- Preserve the existing port, database name, DB user, DB password, alias, group code, and group name.
- Read-only tenant DB connection verification after the temporary update.
- `SELECT 1` only if the connection succeeds.
- Transaction commit only if the connection and `SELECT 1` both pass.
- Transaction rollback if the connection or `SELECT 1` fails.

Not allowed:

- Updating the port.
- Updating the database name.
- Updating the DB user.
- Updating the DB password.
- Updating the alias.
- Updating the group code or group name.
- Creating a tenant DB.
- Creating a tenant DB account.
- Granting tenant DB permissions.
- Running migration.
- Running endpoint or browser smoke.
- Running tenant provisioning.
- Modifying code or tests.
- Creating a new tenant.

## 6. Future Success Criteria

| check | required result |
|---|---|
| selected_target_count | 1 |
| metadata_complete_before_update | yes |
| db_host_input_received | yes |
| db_host_update_rows | 1 |
| port_updated | 0 |
| database_name_updated | 0 |
| db_user_updated | 0 |
| db_password_updated | 0 |
| alias_updated | 0 |
| tenant_connection_after_update | pass |
| select_1_after_update | pass |
| transaction_committed | 1 |
| transaction_rolled_back | 0 |
| repair_success | 1 |

## 7. Future Rollback Criteria

Rollback if any of the following occurs:

- `selected_target_count` is not 1.
- DB host input is empty.
- The DB host update affects anything other than 1 selected row.
- Port changes.
- Database name changes.
- DB user changes.
- DB password changes.
- Alias changes.
- Group code or group name changes.
- The post-update tenant connection fails.
- The post-update `SELECT 1` fails.
- A timeout occurs.
- An unknown operational error occurs.
- Any prohibited field is changed.

## 8. Safety Notes

- No code was modified.
- No test was modified.
- No database SELECT was performed in this planning step.
- No database write was performed in this planning step.
- No tenant DB connection test was performed in this planning step.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No legacy code was executed.
- No new tenant was created.
- No S3 access was performed.
- No presigned URL was generated.
- No secrets were recorded.
- No local-only labels were recorded.
- No raw identifiers were recorded.
- `.env` contents were not printed.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 9. Conclusion

- The next repair candidate is selected-target DB host metadata only.
- The correction requires separate user approval.
- The correction must be limited to exactly 1 re-identified selected row.
- The transaction must commit only if the read-only tenant DB connection and `SELECT 1` both pass.
- Port, database name, DB user, DB password, alias, group code, group name, tenant DB schema, tenant DB accounts, and tenant DB permissions must remain unchanged.
