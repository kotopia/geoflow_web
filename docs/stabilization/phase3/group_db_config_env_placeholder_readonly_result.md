# Group DB Config Environment Placeholder Read-only Result

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: e5da093 phase3: plan selected tenant db user metadata correction
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Determine whether dynamic tenant connection metadata is resolved through environment variables or used directly.
- Check whether the selected target contains placeholder-like host, database user, or password metadata.
- Explain why earlier host and database-user comparisons may have appeared inconsistent.
- Compare the connection source used by the representative static tenant and the selected dynamic tenant.

## 3. Scope

- Code inspection was read-only.
- Central database access was SELECT only.
- Target selection was performed through a local-only numbered list.
- Stored metadata values were not printed.
- Password was not requested, printed, or compared.
- No tenant database connection was attempted.
- No database write or migration was performed.
- No code was modified.
- No endpoint or browser was executed.
- No git add, commit, or push was performed.

## 4. Sanitized Result

| check | result |
|---|---|
| selected_target_count | 1 |
| placeholder_resolution_present | no |
| placeholder_values_used_as_literal | yes, if such values were stored |
| selected_host_placeholder_like | no |
| selected_db_user_placeholder_like | no |
| selected_db_password_placeholder_like | no |
| selected_placeholder_field_count | 0 |
| selected_tenant_host_match | yes |
| selected_tenant_db_user_match | no |
| representative_tenant_uses_static_env | yes |
| selected_tenant_uses_dynamic_group_db_config | yes |

## 5. Code Path Findings

### 5.1 Representative Static Tenant

- Django settings define a representative static tenant connection entry.
- Its database name, host, port, user, and password are populated through environment-backed `TENANT_DB_*` settings and documented fallback sources.
- When an alias is already registered in Django connection settings, tenant connection preparation uses that existing registered entry without reloading `group_db_config`.
- The representative static tenant therefore uses the static environment-backed connection source.

### 5.2 Selected Dynamic Tenant

- The selected target alias was previously verified as absent from static Django database settings.
- Its runtime branch is dynamic `group_db_config` registration.
- The dynamic registration code reads `db_name`, `db_host`, `db_port`, `db_user`, and `db_password` from the central metadata model.
- It assigns those values directly to the Django connection `NAME`, `HOST`, `PORT`, `USER`, and `PASSWORD` fields.
- No environment-variable expansion, placeholder substitution, or fallback helper is called for these fields on the dynamic path.
- Connection options are inherited from the base connection, but the listed connection values come directly from `group_db_config`.

## 6. Placeholder Interpretation

- No placeholder-like syntax was detected in the selected target host, database user, or password fields.
- The selected row therefore contains ordinary stored values rather than recognized environment references.
- The application has no dynamic placeholder resolution step for `group_db_config` connection fields.
- If a placeholder-like string were stored in one of these fields, the current code would pass it as a literal connection value rather than resolving it through the environment.
- For the selected target, this literal-placeholder risk was not detected because the placeholder field count was zero.

## 7. Comparison Result Interpretation

- The selected host matched the locally known actual host.
- The selected database user did not match the locally known PostgreSQL connection role.
- Environment substitution does not explain this difference because the selected tenant uses dynamic metadata and no placeholder resolution is present.
- A prior result may appear different if a different local-only row was selected, if the representative static tenant was compared with the selected dynamic tenant, or if an application login user was mistaken for the PostgreSQL connection role.
- `db_user` means the PostgreSQL role supplied to Django as `USER`. It does not mean the web login user, email, or application user identifier.
- The current selected-target result supports a database-user metadata mismatch while host, port, and database name remain matched.

## 8. Source Comparison

| tenant category | connection source | environment substitution |
|---|---|---|
| representative static tenant | pre-registered Django connection built from environment-backed settings | performed while Django settings are loaded |
| selected tenant | dynamic Django connection built from central `group_db_config` | not performed for metadata fields |

The two tenants do not use the same connection-value source, even though both ultimately produce entries in the Django connection registry.

## 9. Recommended Next Action

- Keep the selected tenant on the dynamic `group_db_config` correction path.
- Treat only `db_user` as the currently confirmed metadata correction candidate.
- Confirm locally that the proposed value is the PostgreSQL connection role and not a web login account.
- Do not modify host, port, or database name because those values matched.
- Do not assess or modify the password in the database-user-only correction step.
- Do not attempt to solve the selected tenant mismatch by changing `TENANT_DB_*` environment settings; those settings govern the representative static connection, not this selected dynamic target.
- Require separate explicit approval before any database write or tenant connection verification.

## 10. Safety Notes

- No code was modified.
- Central database access was SELECT only.
- No database write was performed.
- No tenant database connection was attempted.
- No password was requested, printed, or compared.
- No host, database user, or password was modified.
- No migration was performed.
- No endpoint was called.
- No browser was executed.
- No sensitive value or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 11. Conclusion

- `placeholder_resolution_present`: no.
- `placeholder_values_used_as_literal`: yes if stored, because the dynamic path performs no substitution.
- `selected_tenant_host_match`: yes.
- `selected_tenant_db_user_match`: no.
- `representative_tenant_uses_static_env`: yes.
- `selected_tenant_uses_dynamic_group_db_config`: yes.
- The selected metadata contains no detected placeholder-like host, user, or password value.
- The next safe candidate remains a separately approved correction of the selected row's PostgreSQL database user metadata only.
