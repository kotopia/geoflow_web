# Selected Tenant Attachment Migration Execution Plan

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: a9025d7 phase3: confirm selected tenant migration backup readiness
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define the exact execution mechanism for applying the attachment migration sequence to one selected tenant only.
- Target `webgisapp` migration 0018, with expected application of 0015, 0016, 0017, and 0018.
- Preserve the confirmed backup and restore readiness.
- Prevent accidental central, representative, or all-tenant migration.
- Document the command candidate without executing it.

## 3. Confirmed Readiness

| readiness item | result |
|---|---|
| selected tenant precheck | passed |
| selected target count | exactly 1 |
| tenant connection | passed |
| predecessor migrations 0013 and 0014 | applied |
| target migrations 0015 through 0018 | unapplied |
| target tables | absent |
| table, index, and constraint conflicts | none detected |
| prerequisite schema and function checks | passed |
| backup readiness | confirmed |
| restore readiness | confirmed |
| responsible operator | confirmed |
| user execution permission intent | yes |
| migration execution authorization | pending exact command review |

## 4. Exact Target Scope

- Target database scope: selected tenant only.
- Target application label: `webgisapp`.
- Migration target: `0018`.
- Expected newly applied range: `0015`, `0016`, `0017`, and `0018`.
- Expected predecessor behavior: 0013 and 0014 remain applied and are not rerun.
- Broad all-tenant migration commands are prohibited.
- The representative tenant must not be targeted.
- The central database must not be targeted for `webgisapp` migrations.

## 5. Command Routing Finding

- The selected tenant alias is dynamically sourced and is not a static Django database command choice.
- A direct command using an unregistered selected alias is not a valid execution mechanism.
- The database router permits tenant migration only when the command database equals the process-local default tenant alias setting.
- If a dynamic alias were registered without adjusting that process-local setting, migration operations could be skipped by the router while migration history handling still proceeds.
- Therefore, a plain direct CLI migration command is prohibited for this selected dynamic tenant.

## 6. Prohibited Direct Command Form

Do not execute this direct pattern:

```text
python manage.py migrate webgisapp 0018 --database <selected-dynamic-alias>
```

Reasons:

- The dynamic alias is not available as a static command choice at process start.
- The tenant router compares migration scope with the process-local default tenant alias setting.
- The command does not itself load the selected central metadata and register the dynamic connection.
- A router-denied schema operation combined with migration-history progression would create a serious mismatch risk.

## 7. Required Local-only Execution Wrapper

The approved future mechanism must be a one-process local-only wrapper that performs all of these steps before calling Django migration code:

1. Initialize Django from the clean worktree.
2. Query selectable central metadata read-only.
3. Display a local-only numbered target list.
4. Require one selected target and reject any other count.
5. Load the selected connection metadata without printing it.
6. Register the selected connection in both the active Django connection registry and the settings database registry.
7. Verify the connection handler can resolve the registered alias.
8. Save the original process-local default tenant alias setting.
9. Set the process-local default tenant alias to the selected alias for this wrapper process only.
10. Verify the router returns allow for `webgisapp` migration on the selected alias.
11. Verify the router does not redirect the operation to the central or representative database.
12. Generate and inspect the migration plan.
13. Require the plan to contain exactly 0015 through 0018 for `webgisapp` and no unexpected migration.
14. Only after all guards pass, invoke the exact migration call candidate.
15. Restore process-local settings and close the dynamic connection in a `finally` path.

No alias, connection value, credential, target label, or raw identifier may be printed or recorded.

## 8. Exact Programmatic Command Candidates

After the wrapper has registered and validated the local-only `selected_alias`, the plan-only call candidate is:

```python
call_command(
    "migrate",
    "webgisapp",
    "0018",
    database=selected_alias,
    plan=True,
    interactive=False,
    verbosity=1,
)
```

The execution call candidate, which remains unexecuted and requires separate approval, is:

```python
call_command(
    "migrate",
    "webgisapp",
    "0018",
    database=selected_alias,
    interactive=False,
    verbosity=1,
)
```

These calls are valid candidates only inside the guarded wrapper after dynamic registration and process-local router scope alignment. They must not be copied into an unguarded generic shell.

## 9. Pre-execution Guard Sequence

Immediately before the migration call, recheck:

- Selected target count equals one.
- The selected alias is not the central alias.
- The selected alias is not the representative static alias.
- The selected connection is registered and resolvable.
- Read-only connection and `SELECT 1` pass.
- Migrations 0013 and 0014 remain applied.
- Migrations 0015 through 0018 remain unapplied.
- The three target tables remain absent.
- Target table, explicit index, and explicit constraint conflicts remain zero.
- Required schemas, functions, tables, and predecessor columns remain present.
- Backup and restore readiness remain confirmed.
- The migration plan contains only the expected selected-tenant actions.

## 10. Stop Conditions

Stop before migration execution if any condition occurs:

- Target count is not exactly one.
- Selected alias identity is ambiguous.
- Selected alias resolves to the central or representative database.
- Dynamic connection registration or handler resolution fails.
- Router migration permission is false for the selected alias.
- Router behavior cannot be proven selected-tenant-only.
- Connection or `SELECT 1` fails.
- Predecessor state changed.
- Any target migration is unexpectedly applied.
- Any target table or conflict object unexpectedly exists.
- The plan includes migrations outside expected 0015 through 0018.
- Backup, restore, or responsible operator readiness is no longer confirmed.
- A sensitive value or raw identifier would be exposed.
- Any warning or error is not understood.

## 11. Execution Controls

- Run from a fresh PowerShell process in the required clean worktree.
- Use hidden and local-only connection metadata already stored in the central configuration.
- Use the selected tenant connection only.
- Do not use multi-tenant migration helpers.
- Do not use `--fake`, `--fake-initial`, `--run-syncdb`, or `--prune`.
- Do not alter migration files or history manually.
- Capture only sanitized migration counts, pass or fail states, and failure categories.
- Stop immediately after the exact 0018 target completes or fails.

## 12. Expected Migration Effects

- Apply migration 0015 and create the attachment table with its indexes and uniqueness.
- Apply migration 0016 and add soft-delete fields.
- Apply migration 0017 and add attachment kind and self-parent relationship.
- Apply migration 0018 and create process-event and process-event-attachment tables with indexes, foreign keys, and uniqueness.
- Record exactly four new `webgisapp` migration history rows.
- Do not rerun 0013 or 0014.
- Do not modify central metadata or tenant business-data rows.

## 13. Immediate Postcheck List

After a future approved execution, perform read-only checks:

- Migration command exit status is successful.
- Migration records 0015, 0016, 0017, and 0018 are each present exactly once.
- Attachment table exists.
- Process-event table exists.
- Process-event-attachment table exists.
- Expected columns are present.
- Expected explicit indexes are present.
- Expected foreign keys and unique constraint are present.
- No unexpected migration was recorded.
- No unexpected schema object was created.
- Tenant connection passes.
- Read-only `SELECT 1` passes.
- No raw error or sensitive value was printed.

## 14. Deferred Application-level Postcheck

Only after migration execution is documented and separately approved for browser verification:

- Login remains successful.
- Tenant selection remains successful.
- Tenant home remains available.
- Contracts list remains available.
- Contract detail no longer reports the missing attachment table category.
- No create, update, delete, upload, download, or S3 workflow is intentionally triggered.

## 15. Rollback and Recovery Position

- Do not automatically reverse the migrations after application use begins because reverse operations drop tables or columns and are destructive.
- If execution fails inside Django's migration transaction, capture the sanitized state and stop.
- If an unexpected committed schema state occurs, do not improvise with fake migration records or manual DDL.
- Use the confirmed snapshot-based recovery path under the responsible operator's control if recovery is required.
- Any restore operation requires its own operational decision and documentation.

## 16. Not Performed in This Planning Task

- No migration command was executed.
- No database read or write was performed.
- No table, column, index, or constraint was changed.
- No code or test was modified.
- No endpoint was called.
- No browser was executed.
- No S3 or presigned URL operation was performed.
- No git add, commit, or push was performed.

## 17. Safety Notes

- No host, database name, database user, password, alias, snapshot identifier, instance name, ARN, UUID, tenant label, email, session value, filesystem path, or raw identifier was recorded.
- The exact command candidates contain no real alias or credential.
- Migration execution remains pending separate approval after exact wrapper review.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.

## 18. Conclusion

- Selected tenant precheck passed and backup readiness is confirmed.
- The correct scope is selected tenant only, targeting `webgisapp` 0018 with expected application of 0015 through 0018.
- A plain direct CLI command is unsafe for this dynamically registered tenant.
- The future execution must use a guarded local-only wrapper that registers the selected connection and aligns router scope in-process.
- The exact programmatic migration call is documented but was not executed.
- Migration execution remains a separate explicitly approved step.
