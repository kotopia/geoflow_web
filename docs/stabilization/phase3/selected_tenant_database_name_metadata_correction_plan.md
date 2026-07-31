# Selected Tenant Database Name Metadata Correction Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: a794222 phase3: document selected tenant db driver auth diagnostic
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Background

- Direct pgAdmin connection succeeds according to the user.
- Previous selected tenant credential correction attempts failed or were rolled back.
- SSL option variants did not produce a successful application-style connection.
- psql, psycopg2, and psycopg diagnostics did not find a successful path using the selected central metadata target.
- The user then compared the pgAdmin configuration with the selected central metadata target.
- The user reported that the host is likely the same, the port is the same, the user is the same, but the database name is different.
- SSL, SSH tunnel, and VPN status remain unknown.
- The database name mismatch is now the primary suspected cause.

## 3. Purpose

- Define a safe correction plan for the selected tenant central metadata `database_name` field.
- Limit any future correction to the selected 1 target only.
- Do not change the DB user or password in this correction.
- Do not change the host or port in this correction.
- Do not create a new tenant.
- Do not modify tenant DB schema, users, permissions, or data.

## 4. Current Sanitized Finding

| check | result |
|---|---|
| host_comparison | likely_same |
| port_comparison | same |
| database_name_comparison | different |
| user_comparison | same |
| ssl_status | unknown |
| ssh_tunnel_status | unknown |
| vpn_status | unknown |
| primary_suspected_cause | database_name_metadata_mismatch |

## 5. Future Correction Scope

Allowed after separate user approval:

- Central DB SELECT to locate selectable candidates.
- Local-only target number selection.
- Local-only confirmation that the selected target matches the pgAdmin connection target.
- Local-only input of the correct PostgreSQL database name.
- Central DB UPDATE of `database_name` only for exactly 1 selected `group_db_config` row.
- No DB user or password update.
- No host update.
- No port update.
- No alias update.
- Read-only tenant DB connection verification after the update.
- `SELECT 1` only if the connection succeeds.
- Transaction rollback if post-update connection verification fails.
- Commit the transaction only if the post-update connection and `SELECT 1` pass.

Not allowed:

- Updating the DB user or password.
- Updating the host.
- Updating the port.
- Updating the alias.
- Updating the group code or group name.
- Creating a tenant DB.
- Creating a tenant DB account.
- Granting tenant DB permissions.
- Running migration.
- Running endpoint or browser smoke.
- Running tenant provisioning.
- Modifying code or tests.

## 6. Future Success Criteria

| check | required result |
|---|---|
| selected_target_count | 1 |
| metadata_complete_before_update | yes |
| database_name_update_rows | 1 |
| host_updated | 0 |
| port_updated | 0 |
| db_user_updated | 0 |
| db_password_updated | 0 |
| tenant_connection_after_update | pass |
| select_1_after_update | pass |
| transaction_committed | 1 |
| transaction_rolled_back | 0 |
| repair_success | 1 |

## 7. Future Rollback Criteria

Rollback if any of the following occurs:

- `selected_target_count` is not 1.
- The correct database name input is empty.
- The database name update affects anything other than 1 row.
- The post-update tenant connection fails.
- The post-update `SELECT 1` fails.
- Credential rejection appears after the database name correction.
- A timeout or unknown operational error appears after the database name correction.
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

- The next repair candidate is not the DB user or password.
- The next repair candidate is the selected tenant central metadata database name.
- A database name correction requires separate user approval.
- The correction must be limited to exactly 1 selected row and must roll back unless the read-only tenant connection and `SELECT 1` pass.
