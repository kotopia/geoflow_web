# Attachment Table Schema Diagnostic Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: 996a6e2 phase3: document selected tenant readonly browser smoke retry
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define a read-only diagnostic plan for the contract detail failure caused by a missing attachment table.
- Determine whether the expected model table, migration state, and selected tenant schema agree.
- Keep connection repair and schema repair as separate workstreams.
- Avoid migrations, table creation, code changes, and tenant data changes in the diagnostic step.

## 3. Confirmed Context

- Login passed in the selected tenant browser smoke.
- Tenant selection passed.
- Tenant home passed.
- Contracts list passed.
- No tenant connection error was observed.
- Contract detail failed because the expected `ops.attachments` table was missing.
- Tenant connection behavior is therefore validated through the contracts list.
- The remaining contract detail failure is classified as a tenant schema or table issue.

## 4. Diagnostic Questions

The read-only diagnostic should answer:

1. What database table name does the current `Attachment` model expect?
2. Is the attachment model managed by Django or declared unmanaged?
3. Which application label and migration identity own the expected table?
4. Which migration operation is expected to create or adopt the table?
5. Is that migration present in source control?
6. Does Django report the migration as applied for the selected tenant?
7. Does the expected table physically exist in the selected tenant database?
8. Are there similarly named legacy tables or schema-qualified variants?
9. Do model fields match any existing legacy table structure?
10. Is the problem a missing migration, unapplied migration, table rename, schema search-path mismatch, or unmanaged-model mismatch?

## 5. Phase A: Static Code Inspection

- Locate the current `Attachment` model definition.
- Record its app label, model name, `Meta.db_table`, and `Meta.managed` state.
- Identify relationships referenced by contract detail.
- Locate all migrations that create, rename, alter, or delete the attachment model or table.
- Inspect migration dependencies without editing them.
- Check for legacy model identities or compatibility mappings.
- Inspect the contract detail query path to confirm which model triggers the missing-table access.
- Do not execute application endpoints during this inspection.

## 6. Phase B: Read-only Selected Tenant Inspection

This phase requires separate explicit approval for tenant database SELECT access.

- Connect to the already validated selected tenant using the approved read-only method.
- Query database catalog metadata only.
- Check whether the exact expected attachment table exists.
- Check for similarly named tables without recording identifying connection values.
- Check table schema and column presence using boolean or count-only results.
- Inspect the selected tenant migration history table read-only for relevant migration records.
- Do not query attachment business-data rows unless separately approved and necessary.
- Do not print tenant alias, database name, host, credentials, object keys, filenames, UUIDs, or raw identifiers.

## 7. Sanitized Result Matrix

A future diagnostic result should use this structure:

| check | allowed result |
|---|---|
| expected_attachment_table_identified | yes/no |
| attachment_model_managed | yes/no/unclear |
| creating_migration_found | yes/no/unclear |
| migration_record_present | yes/no/not_tested |
| expected_table_present | yes/no/not_tested |
| similar_legacy_table_present | yes/no/not_tested |
| expected_columns_complete | yes/no/not_tested |
| schema_search_path_issue_possible | yes/no/unclear |
| diagnostic_category | sanitized category only |

## 8. Possible Diagnostic Categories

- `model_table_mapping_mismatch`
- `migration_missing_from_source`
- `migration_not_applied`
- `migration_record_table_mismatch`
- `legacy_table_name_mismatch`
- `unmanaged_model_expectation_mismatch`
- `schema_search_path_mismatch`
- `table_present_column_mismatch`
- `unknown_schema_issue`

These categories are diagnostic labels only and do not authorize a repair.

## 9. Decision Rules

- If the model is managed and a creating migration exists but is not applied, prepare a tenant migration impact review.
- If the migration is recorded as applied but the table is absent, stop and investigate migration history or manual schema drift.
- If a compatible legacy table exists under another name, prepare a mapping or migration design; do not rename it automatically.
- If the model is unmanaged, identify the intended external table ownership before proposing any creation.
- If the expected table exists outside the active schema search path, prepare a connection/schema configuration analysis.
- If columns differ, document the differences using counts and booleans before designing a repair.

## 10. Explicitly Prohibited During Diagnosis

- Running `migrate`, `makemigrations`, or tenant migration commands
- Creating, renaming, altering, or dropping a table
- Inserting, updating, or deleting database rows
- Editing models, migrations, settings, routers, views, or tests
- Calling contract, attachment, upload, or delete endpoints
- Running browser smoke
- Accessing S3 or generating presigned URLs
- Recording connection values, credentials, tenant identifiers, attachment identifiers, filenames, or raw errors
- Git add, commit, or push

## 11. Recommended Next Step

- Execute Phase A as a code-only read-only audit first.
- Based on the static result, request separate approval for the minimum selected-tenant catalog and migration-history SELECT queries.
- Produce a sanitized diagnostic result before proposing any migration or table repair.
- Do not run migrations yet.
- Do not create the missing table yet.

## 12. Safety Notes

- No database read or write was performed by this planning task.
- No migration was performed.
- No table was created, altered, renamed, or dropped.
- No code or test was modified.
- No endpoint was called.
- No browser was executed.
- No S3 or presigned URL operation was performed.
- No sensitive value or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 13. Conclusion

- The tenant connection is validated through the contracts list.
- Contract detail is blocked by a missing `ops.attachments` table.
- The next task should be a read-only model, migration, and selected-tenant schema diagnostic.
- Migration execution and table creation remain prohibited until the diagnostic result is reviewed and separately approved.
