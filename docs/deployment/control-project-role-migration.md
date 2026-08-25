# Control DB project role migration

The central tenant roles are renamed without changing their UUIDs, assignments,
or permission mappings:

- `project_manager` → `project_admin` (`프로젝트 관리자`)
- `project_leader` → `project_coordinator` (`프로젝트 코디네이터`)

The project-local values in `prj.project_members.member_role` remain
`project_manager` and `project_leader`.

## Rehearsal

Run `scripts/ops/migrate_control_project_roles.py` against an isolated copy of
the Control DB. It rolls back by default and reports assignment and permission
counts without printing user or business records.

Apply only after explicit production authorization:

```text
python scripts/ops/migrate_control_project_roles.py --apply
```

The script locks `roles`, rejects missing sources or pre-existing target codes,
updates exactly two rows, and verifies that assignments and permissions still
join through the unchanged role IDs. Rollback before application is unnecessary
because dry-run never commits. After application, the SQL rollback is the inverse
code/name update, provided no target-code role has subsequently been created.

Deploy application code before applying the Control DB change. The application
temporarily recognizes the two legacy codes as compatibility aliases, so this
ordering does not create an authorization gap. After the database change,
invalidate active authorization sessions (or restart the service as a separately
approved deployment action) so users receive canonical role codes immediately.
