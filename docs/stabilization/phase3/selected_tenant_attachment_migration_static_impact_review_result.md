# Selected Tenant Attachment Migration Static Impact Review Result

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 5f66f49 phase3: plan selected tenant attachment migration impact review
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Review `webgisapp` migrations 0015 through 0018 without importing or executing them.
- Identify tables, columns, indexes, constraints, dependencies, data operations, and reverse behavior.
- Assess the risk of applying the sequence to the selected tenant.
- Determine whether selected-tenant-only execution is more appropriate than a broader rollout.

## 3. Scope

- Migration and model source files were read only.
- No migration module was imported or executed.
- No database connection was made.
- No database read or write was performed.
- No table, column, index, or constraint was created, altered, or dropped.
- No code or test was modified.
- No endpoint or browser was executed.
- No git add, commit, or push was performed.

## 4. Migration Identity and Chain

- The migration files are stored under the operational application migration package.
- The application configuration uses the historical migration label `webgisapp`.
- The inspected chain is strictly linear:

| migration | direct dependency |
|---|---|
| 0015 | 0014 |
| 0016 | 0015 |
| 0017 | 0016 |
| 0018 | 0017 |

- Applying a target through 0018 may also apply 0014 or earlier prerequisites if they are not already recorded.
- The selected tenant's exact predecessor state must therefore be confirmed before execution.

## 5. Migration 0015 Impact

### 5.1 Operation

- Creates managed model table `ops.attachments`.
- Uses standard Django `CreateModel` only.
- Contains no `RunSQL` and no `RunPython`.
- Contains no explicit data migration.

### 5.2 Columns

| column category | behavior |
|---|---|
| identifier | UUID primary key with generated default |
| entity reference | entity type and UUID entity identifier |
| purpose | required text |
| object storage reference | required unique text key |
| display metadata | original name and optional MIME type |
| integrity metadata | optional size and digest |
| state and ordering | active flag and integer order with defaults |
| auxiliary metadata | JSON value with empty-object default |
| timestamps | creation and update timestamps |

### 5.3 Indexes and Constraints

- Primary-key constraint on the UUID identifier.
- Unique constraint on the object storage reference.
- Composite index on entity type and entity identifier.
- Composite index on entity type, entity identifier, purpose, and order.
- No foreign-key constraint is declared by this migration.

### 5.4 Reverse and Risk

- Django can reverse `CreateModel` by dropping the created table.
- Reverse is structurally available but destructive because all attachment rows would be lost.
- Forward risk for an empty, conflict-free target is medium due to table, indexes, and uniqueness creation.

## 6. Migration 0016 Impact

### 6.1 Operation

- Adds three soft-delete fields to `ops.attachments`.
- Uses three standard Django `AddField` operations.
- Contains no `RunSQL` and no `RunPython`.
- Contains no explicit data migration.

### 6.2 Columns

| column | behavior |
|---|---|
| deleted timestamp | nullable timestamp |
| deleted-by marker | nullable text |
| deleted flag | non-null boolean with false default |

### 6.3 Indexes and Constraints

- No explicit new index is declared.
- No explicit new constraint is declared.
- Adding the non-null boolean default may require database work for pre-existing rows, although the selected tenant currently lacks the table.

### 6.4 Reverse and Risk

- Django can reverse the fields by dropping the three columns.
- Reverse is structurally available but discards any values stored in those columns.
- Forward risk is low to medium after 0015 succeeds, depending on table size and database default behavior.

## 7. Migration 0017 Impact

### 7.1 Operation

- Adds an attachment kind field.
- Adds an optional self-referencing parent relationship.
- Uses standard Django `AddField` operations.
- Contains no `RunSQL` and no `RunPython`.
- Contains no explicit data migration.

### 7.2 Columns and Constraints

| item | behavior |
|---|---|
| kind | non-null text with a file default |
| parent identifier | nullable foreign key to the same attachment table |
| parent delete behavior | sets child parent reference to null |
| reverse relation | exposes derivative attachments through model state |

- The foreign key creates a self-referencing database constraint.
- Django normally creates an index for the foreign-key column unless backend behavior or migration SQL indicates otherwise.

### 7.3 Reverse and Risk

- Django can reverse the migration by removing both fields and the associated relationship constraint.
- Reverse is structurally available but discards kind and parent relationship data.
- Forward risk is medium because it adds a self-referencing foreign key and a non-null defaulted field.

## 8. Migration 0018 Impact

### 8.1 Process Event Table

- Creates managed table `ops.process_events`.
- Uses standard Django `CreateModel`.

Columns include:

- UUID primary key
- scope type and scope identifier
- stage and event type
- title and memo
- status with application-level choices and a default
- optional occurrence and due dates
- required creator marker
- creation and update timestamps

Indexes include:

- scope type plus scope identifier
- scope type, scope identifier, and stage
- status

No foreign key is declared on the generic scope identifier.

### 8.2 Process Event Attachment Link Table

- Creates managed table `ops.process_event_attachments`.
- Uses standard Django `CreateModel`.

Columns and relationships include:

- UUID primary key
- role with application-level choices and a default
- non-negative order with a default
- creation timestamp
- required foreign key to `ops.attachments`
- required foreign key to `ops.process_events`
- cascade delete behavior for both relationships

Indexes and constraints include:

- Composite index on event and order.
- Unique constraint on event and attachment.
- Foreign-key constraints to both parent tables.
- Django normally creates indexes for foreign-key columns.

### 8.3 Data Operations, Reverse, and Risk

- Contains no `RunSQL` and no `RunPython`.
- Contains no explicit data migration.
- Django can reverse both `CreateModel` operations by dropping the tables.
- Reverse is structurally available but destructive to all process-event and link rows.
- Forward risk is medium because two tables, multiple indexes, foreign keys, cascade behavior, and uniqueness are created.

## 9. Data Migration and Custom Operation Summary

| migration | data migration | RunPython | RunSQL | operation type |
|---|---|---|---|---|
| 0015 | no | no | no | CreateModel |
| 0016 | no | no | no | AddField |
| 0017 | no | no | no | AddField and foreign key |
| 0018 | no | no | no | CreateModel |

- None of 0015 through 0018 explicitly copies, transforms, inserts, updates, or deletes business data.
- Defaulted non-null fields may still cause database-level work during schema application.
- Migration history writes and schema DDL are inherent in migration execution even without a data migration.

## 10. Reverse Behavior Summary

| migration | framework reverse available | practical consequence |
|---|---|---|
| 0015 | yes | drops attachment table and its data |
| 0016 | yes | drops soft-delete columns and their data |
| 0017 | yes | drops kind and parent columns and relationship data |
| 0018 | yes | drops process-event and link tables and their data |

- The four migrations use reversible Django operations.
- Reversal is not data-safe after application use begins.
- A database backup is still required before forward execution.

## 11. Critical Predecessor Finding

- Migration 0015 directly depends on 0014.
- Migration 0014 uses `SeparateDatabaseAndState`.
- Its database operation executes custom SQL that adds nullable address columns to an employee profile table if missing.
- It also invokes a schema-version bump function.
- Its state operation creates an unmanaged model state entry.
- Its database reverse is explicitly a no-op.
- Migration 0014 depends on 0013, which installs or replaces the schema-version bump function and also has a no-op reverse.

This means an execution request framed as 0015 through 0018 may have additional DDL and schema-version effects if 0013 or 0014 is not already applied. The exact applied state through 0014 is a mandatory precheck.

## 12. Current Model Alignment

- The current `Attachment` model is managed and maps to the table created by 0015.
- It includes the soft-delete fields added by 0016.
- It includes the kind and self-parent fields added by 0017.
- The current managed process-event models map to the two tables created by 0018.
- Current model indexes and uniqueness definitions align with the inspected migration declarations.
- The historical application label remains part of the migration identity and must not be changed as part of this work.

## 13. Risk Assessment

| area | risk | reason |
|---|---|---|
| 0015 | medium | Creates a managed table with uniqueness and composite indexes. |
| 0016 | low to medium | Adds three columns, including a non-null defaulted flag. |
| 0017 | medium | Adds a non-null defaulted field and self-referencing foreign key. |
| 0018 | medium | Creates two tables, foreign keys, cascade relationships, indexes, and uniqueness. |
| dependency chain | medium to high until prechecked | Unapplied 0013 or 0014 would introduce custom SQL, schema-version mutation, and no-op reverse behavior. |
| broad tenant rollout | high | Other tenant schemas and migration histories have not been individually reviewed. |

Selected-tenant execution risk can be reduced to medium only after backup readiness, predecessor verification, conflict checks, and exact command scope are confirmed.

## 14. Selected Tenant Only Decision

- Selected-tenant-only application is the appropriate next rollout scope if execution is later approved.
- The selected tenant has a confirmed business symptom, validated connection, absent target tables, and absent 0015 through 0018 records.
- Other tenants have not been individually inspected for prerequisites, conflicts, migration gaps, or business readiness.
- Approval for the selected tenant must not authorize an all-tenant migration command.
- A broader rollout requires a separate tenant inventory and per-tenant precheck.

## 15. Required Prechecks Before Execution

- Verify a recoverable selected-tenant backup.
- Verify the selected target is exactly one tenant.
- Verify tenant connection and read-only `SELECT 1` still pass.
- Verify migrations through 0014, especially 0013 and 0014, are recorded and their required objects exist.
- Verify 0015 through 0018 remain unapplied.
- Verify the three target tables remain absent.
- Verify there are no conflicting table, index, constraint, or foreign-key names.
- Verify prerequisite schemas and referenced tables exist.
- Review the exact tenant-scoped migration command without executing it.
- Stop if any observed state differs from this static review.

## 16. Recommended Next Action

- Perform a selected-tenant read-only prerequisite and conflict precheck.
- Give special attention to migrations 0013 and 0014 before targeting 0018.
- Confirm backup and restore readiness.
- Prepare an exact selected-tenant-only migration execution plan with explicit stop conditions.
- Do not run migrations until the precheck result and execution command are separately reviewed and approved.
- Do not use a fleet-wide migration command for this repair.

## 17. Safety Notes

- No migration was executed.
- No database connection was made.
- No database read or write was performed.
- No table, column, index, or constraint was changed.
- No code or test was modified.
- No endpoint was called.
- No browser was executed.
- No sensitive value or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 18. Conclusion

- Migrations 0015 through 0018 contain schema operations only and no explicit data migrations, `RunPython`, or `RunSQL`.
- They create the attachment and process-event schema required by current managed models.
- Their Django operations are reversible, but reversal is destructive to any data created after rollout.
- The 0014 predecessor introduces additional custom SQL and schema-version effects with no-op database reversal.
- Selected-tenant-only application is appropriate only after the exact predecessor state, backup, conflicts, and prerequisites are confirmed.
- Actual migration execution remains prohibited pending separate approval.
