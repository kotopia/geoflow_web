# Selected Tenant Attachment Migration Impact Review Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: e7222cb phase3: document attachment table schema diagnostic
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define the impact review required before applying `webgisapp` migrations 0015 through 0018.
- Identify every schema and data effect in the migration sequence.
- Determine prerequisites, backup requirements, execution scope, and post-migration checks.
- Keep migration execution prohibited until the review is complete and separately approved.

## 3. Confirmed Context

- The selected tenant does not record `webgisapp` migrations 0015 through 0018 as applied.
- The selected tenant does not contain `ops.attachments`.
- The selected tenant does not contain `ops.process_events`.
- The selected tenant does not contain `ops.process_event_attachments`.
- The representative tenant contains the inspected migration records and tables.
- Both selected and representative tenant read-only connections passed.
- The diagnosed condition is `partial_schema_rollout`, with `migration_not_applied` on the selected tenant.
- Contract detail is blocked by the missing attachment table, not by a tenant connection failure.

## 4. Review Scope

The impact review must cover:

- Migration files 0015, 0016, 0017, and 0018
- All declared dependencies
- All schema operations
- All data operations
- All indexes and constraints
- Model state transitions
- Database-specific SQL or functions
- Forward and reverse behavior
- Selected-tenant prerequisites
- Representative-tenant post-state for comparison
- Single-tenant versus multi-tenant rollout policy

## 5. Static Migration Review

For each migration from 0015 through 0018, record:

| review item | required finding |
|---|---|
| migration identity | sanitized migration number and purpose |
| direct dependency | predecessor migration number |
| cross-app dependency | app and migration identity, if present |
| created tables | names or sanitized table categories |
| added or altered columns | field purpose, nullability, and default behavior |
| indexes | index purpose and uniqueness |
| constraints | primary, foreign, unique, check, or exclusion constraints |
| schema-qualified SQL | presence and impact |
| data migration | present or absent |
| custom Python operation | present or absent |
| reverse operation | reversible, irreversible, or unclear |
| lock or runtime risk | low, medium, high, or unclear |

The review must inspect source files only and must not import or execute migration operations.

## 6. Table and Constraint Impact

- Confirm which migration creates `ops.attachments`.
- Confirm which migration creates `ops.process_events`.
- Confirm which migration creates `ops.process_event_attachments`.
- Identify any additional tables created by the sequence.
- List every foreign-key target and verify that the referenced tables are expected to exist before execution.
- Identify indexes, uniqueness rules, and delete behavior.
- Check whether schema creation is assumed or explicitly performed.
- Check whether table names depend on app labels or legacy migration identity.
- Confirm whether the migrations use standard Django operations or raw SQL.
- Identify potential name conflicts with any existing legacy objects.

## 7. Data Change Review

- Determine whether any migration inserts, updates, deletes, copies, transforms, or backfills data.
- Inspect `RunPython`, `RunSQL`, defaults, non-null field additions, and state/database separation operations.
- Identify whether an empty selected-tenant target state is assumed.
- Estimate affected row counts through a separately approved read-only precheck if data operations exist.
- Do not execute migration code during this review.
- If any destructive or irreversible data operation is present, stop and require a separate high-risk review.

## 8. Prerequisite Review

- Confirm that every migration before 0015 is recorded as applied on the selected tenant.
- Confirm that required schemas and extensions exist.
- Confirm that all referenced tables and columns exist.
- Confirm that the selected tenant migration history has no gaps or conflicts before 0015.
- Check for fake-applied migrations or migration records without matching schema objects.
- Check for existing tables that would conflict with creation operations.
- Confirm application and migration labels remain compatible with the historical chain.
- Do not modify migration history manually.

## 9. Rollout Scope Decision

Two decisions must remain separate:

### Option A: Selected Tenant Only

- Appropriate for restoring the currently validated tenant after its exact preconditions are confirmed.
- Limits immediate blast radius.
- Requires documenting why other tenants remain deferred.
- Must not be treated as evidence that every tenant is ready.

### Option B: All Unapplied Tenants

- Requires a complete inventory of tenant migration and schema state.
- Requires per-tenant prechecks and backups.
- Requires explicit handling of heterogeneous or partially migrated tenants.
- Has a broader operational risk and must not be inferred from approval for one tenant.

The impact review must recommend one option. Approval for selected-tenant execution must not authorize a fleet-wide rollout.

## 10. Backup Requirements

Before any future migration execution:

- Create or verify a current recoverable backup of the selected tenant database.
- Record backup completion using a sanitized reference only.
- Confirm the restore procedure and responsible operator.
- Confirm sufficient storage and backup integrity.
- Define the recovery point and acceptable outage window.
- Do not place credentials, hostnames, database names, or raw backup identifiers in documentation.

## 11. Read-only Precheck Requirements

- Confirm the selected target count is exactly one.
- Confirm the tenant connection passes with the repaired credential metadata.
- Confirm migrations 0015 through 0018 remain unapplied.
- Confirm all required predecessor migrations are applied.
- Confirm the three expected tables remain absent.
- Confirm no conflicting table, index, or constraint names exist.
- Confirm prerequisite schemas, extensions, tables, and columns exist.
- Record only counts, booleans, and sanitized categories.
- Stop if observed state differs from the reviewed migration assumptions.

## 12. Proposed Postcheck Requirements

If migration execution is later approved and completed, verify:

- Migrations 0015 through 0018 are recorded exactly once.
- Expected tables exist.
- Expected columns, indexes, and constraints exist.
- No unexpected table or column was created.
- Tenant connection still passes.
- Read-only `SELECT 1` passes.
- Tenant home and contracts list remain available.
- Contract detail reaches the expected read-only response without the missing-table error.
- Attachment reads do not trigger unexpected writes or S3 operations.
- No unexpected traceback or new migration inconsistency is observed.

## 13. Failure and Stop Conditions

Do not authorize or continue migration execution if:

- The target tenant cannot be identified unambiguously.
- Backup or restore readiness is not confirmed.
- Predecessor migration history is incomplete or inconsistent.
- A migration is destructive, irreversible, or includes unreviewed data changes.
- Existing schema objects conflict with migration operations.
- Required schema, extension, table, or column prerequisites are absent.
- More tenants are included than explicitly approved.
- Sensitive values or raw identifiers would be exposed.
- The migration command or database alias scope is ambiguous.

## 14. Future Execution Controls

- Use the exact selected tenant database alias through a locally controlled command without documenting it.
- Run only the reviewed migration target and dependency sequence.
- Do not use broad all-tenant migration commands unless separately approved.
- Capture sanitized command outcome, applied migration count, and postcheck booleans.
- Stop on the first unexpected warning, error, schema difference, or target mismatch.
- Do not fake migration state unless a separate repair design explicitly justifies and approves it.

## 15. Prohibited in This Planning Task

- Running `migrate`, `makemigrations`, or multi-tenant migration commands
- Creating, altering, renaming, or dropping tables
- Writing to any database
- Editing migration, model, settings, router, view, or test files
- Calling endpoints or running browser smoke
- Accessing S3 or generating presigned URLs
- Recording tenant connection values, credentials, identifiers, or raw errors
- Git add, commit, or push

## 16. Recommended Next Step

- Perform the static review of migration files 0015 through 0018 first.
- Produce a migration-by-migration impact result covering schema, data, dependencies, and reversibility.
- Based on that result, request separate approval for selected-tenant read-only prerequisite checks.
- Decide selected-tenant-only versus broader rollout explicitly.
- Do not run migrations until the impact result, backup readiness, target scope, and execution command are all reviewed and approved.

## 17. Safety Notes

- No migration was executed.
- No database read or write was performed.
- No table was created, altered, renamed, or dropped.
- No code or test was modified.
- No endpoint was called.
- No browser was executed.
- No S3 or presigned URL operation was performed.
- No sensitive value or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 18. Conclusion

- The selected tenant is a candidate for a reviewed 0015 through 0018 migration sequence, but execution is not yet authorized.
- Static migration impact review must identify schema operations, data changes, dependencies, reversibility, and conflicts.
- Selected-tenant-only and all-unapplied-tenant rollout decisions must remain separate.
- Backup, precheck, execution, rollback, and postcheck requirements must be approved before any migration runs.
