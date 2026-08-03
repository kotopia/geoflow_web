# Tenant Connection Source-of-Truth Code Audit Result

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 0d18eb1 phase3: plan selected tenant db host metadata correction
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Audit Context

- The audit was performed after a selected tenant connection continued to fail despite sanitized metadata correction attempts.
- The purpose was to determine which configuration source the runtime application actually uses for tenant database connections.
- This was a static code audit only. It did not validate any real connection value or execute a tenant connection.

## 3. Scope

- Code inspection only
- No database SELECT
- No database write
- No tenant database connection
- No migration
- No endpoint call
- No browser smoke
- No S3 access
- No presigned URL work
- No code or test change
- One documentation file created

## 4. Files Inspected

| file | audit purpose |
|---|---|
| `geoflow_project/settings.py` | Inspect static database definitions, environment-backed tenant settings, and the default tenant alias setting. |
| `control/middleware.py` | Identify how session state becomes request-local tenant routing context. |
| `control/db_router.py` | Identify how operational models select a database alias and how missing aliases fail closed. |
| `control/tenant_connections.py` | Identify connection registration order and the mapping from central metadata to Django connection settings. |
| `control/views_auth.py` | Trace selectable candidate creation, direct routing, and post-login connection preparation. |
| `control/views_groups.py` | Trace group selection validation and selected alias storage. |
| `control/models.py` | Confirm the fields provided by the central group database configuration model. |
| `control/services/central_repo.py` | Inspect central candidate lookup and alternate alias resolution behavior. |
| `control/services_people.py` | Inspect an additional central-to-tenant alias consumer. |
| `geoflow_ops/views_contracts.py` | Confirm the database alias used by contract list and detail queries. |
| `geoflow_ops/views_uploads.py` | Confirm the database alias used by attachment queries. |
| `geoflow_ops/urls.py` | Confirm the operational route definitions associated with the audited views. |

## 5. Tenant Alias Resolution

| stage | source | result |
|---|---|---|
| selectable candidate creation | active central membership, active group, and complete `group_db_config` metadata | Candidate contains the configuration alias after eligibility checks pass. |
| single selectable candidate | candidate alias | Alias is stored in the tenant session state. |
| multiple selectable candidates | session-stored candidate selected through validated group selection | The validated candidate alias is stored in the tenant session state. |
| request routing | tenant session alias | Tenant middleware prepares the connection and then sets request-local routing context. |
| operational ORM routing | request-local alias returned by `current_db_alias()` | Tenant application queries use the resolved runtime alias. |
| missing tenant context | central alias | Routing remains central unless a valid tenant route has been prepared. |

The request payload and URL are not the tenant connection source. The selected alias originates from central candidate data, is stored in the session, and is then handled by middleware.

## 6. Tenant Connection Source

| condition | runtime connection source | source-of-truth status |
|---|---|---|
| selected alias already exists in the active Django connection registry | existing registered connection settings | Static or previously registered settings take precedence. |
| selected alias is absent from the active Django connection registry | central `group_db_config` after active membership and alias checks | Central metadata is used to build and register the connection. |
| dynamic registration metadata is incomplete or inconsistent | no tenant connection | Preparation fails closed and tenant session context is cleared. |

The runtime source is therefore conditional. `group_db_config` is not consulted again when the selected alias is already registered. A static tenant database entry exists in Django settings, and environment-backed `TENANT_DB_*` settings are used to construct that entry. The default tenant alias setting also exists, but the audited request middleware documents it as a migration or initialization concern rather than the normal request-level selection source.

## 7. group_db_config Field Mapping

| central metadata field | Django connection setting | interpretation |
|---|---|---|
| `db_alias` | connection registry key | Runtime database alias identifier. |
| `db_name` | `NAME` | PostgreSQL database name. |
| `db_host` | `HOST` | PostgreSQL server host. |
| `db_port` | `PORT` | PostgreSQL server port. |
| `db_user` | `USER` | PostgreSQL connection role name, not an application user identifier. |
| `db_password` | `PASSWORD` | PostgreSQL connection credential. |

Dynamic registration copies the base connection structure and inherits its connection options before replacing the listed connection fields. No raw metadata values were inspected or recorded.

## 8. Contracts Route Database Usage

| operation | database alias source |
|---|---|
| contract list | `current_db_alias()` from request-local middleware context |
| contract detail | `current_db_alias()` from request-local middleware context |
| related partner and project reads | the same resolved runtime alias |
| contract attachment reads | the same resolved runtime alias |

The contract views do not independently read `group_db_config`. They rely on the alias already selected and prepared by authentication and middleware. The database router applies the same request-local alias to tenant application models and fails closed if a non-central alias is absent from the active connection registry.

## 9. Diagnostic Script Alignment

The earlier direct connection diagnostic approach was only conditionally aligned with runtime behavior.

- It aligned with the dynamic path when the selected alias was absent and the application would build a connection from `group_db_config`.
- It did not reproduce the runtime short-circuit used when the selected alias was already present in Django connection settings.
- It did not necessarily reproduce inherited Django connection options used by dynamic registration.
- A direct connection result based only on `group_db_config` therefore cannot establish which values the contracts request used.

Diagnostic script alignment status: mismatched for an already registered alias and only partially aligned for dynamic registration.

## 10. Interpretation

- `group_db_config` is an eligibility source and a dynamic registration source, but it is not an unconditional runtime source of truth.
- Existing registered connection settings have higher runtime priority for an already registered alias.
- Static tenant configuration and its environment-backed `TENANT_DB_*` inputs remain a possible source for the selected runtime connection.
- A previously working contracts path could plausibly have used a static registered connection rather than the current central metadata row. This audit does not confirm historical execution.
- Correcting central metadata cannot change runtime behavior while an existing registered alias continues to short-circuit dynamic registration.
- The audited code treats `db_user` as the PostgreSQL connection role through the Django `USER` setting. It does not treat that field as an application login account.
- Contract list, contract detail, and attachment reads all follow the middleware-established request-local alias.

Overall source-of-truth status: ambiguous at the data level and conditional at the code level. The code clearly defines two possible sources, but this read-only audit did not inspect runtime values to determine which branch a specific request used.

## 11. Recommendation

- Pause further `db_host`, database name, database user, and password metadata corrections until the active runtime source is confirmed.
- Prepare a separate read-only runtime-source verification step that checks only whether the selected alias is already registered, without printing the alias or connection values.
- If the alias is already registered, compare sanitized field-presence and source-category results for the registered entry and central metadata. Do not assume central metadata changes will affect the request.
- If the alias is not registered, validate the dynamic registration path, including inherited connection options, before any repair.
- Update any future diagnostic command to follow the same source priority and option handling as `ensure_tenant_connection_for_session()`.
- Do not retry database metadata repair automatically.
- Do not add another environment-specific static alias as a workaround.

## 12. Safety Notes

- No code was modified.
- No test was modified.
- No database SELECT was performed.
- No database write was performed.
- No tenant database connection was attempted.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated.
- No legacy code was executed.
- No tenant was created.
- No environment contents were printed.
- No secrets, aliases, database values, business labels, personal identifiers, session values, raw identifiers, raw exception text, or connection strings were recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 13. Conclusion

- Tenant selection originates from eligible central candidate metadata and becomes session and request-local routing state.
- Tenant connection settings come from an existing registered connection when present, otherwise from validated central `group_db_config` metadata.
- The contracts workflow uses the resulting request-local alias for list, detail, related, and attachment queries.
- Prior direct diagnostics did not fully mirror the existing-connection short-circuit or inherited Django options.
- Further metadata correction should remain paused until a sanitized runtime-source verification identifies which connection source is active.
