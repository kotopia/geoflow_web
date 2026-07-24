# Central Contract Permission Assignment Inspection

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 6de5d1a phase2: design contract write permission hardening
- Working tree expected state: clean

## 2. Purpose

Contract write hardening requires confirmation that `contracts.edit` exists and is assigned to appropriate roles. Attachment delete authorization must not rely on an unconfirmed permission.

This task performed a read-only inspection of central permission metadata. No code change, DB write, migration, delete endpoint call, or S3 action was performed.

## 3. Tables / Code Paths Inspected

Central models and tables identified from `control.models` and the authorization services:

- permission metadata: `permissions`
- role metadata: `roles`
- role-to-permission mapping: `role_permissions`
- user/group-to-role mapping: `user_group_map`

Read-only database inspection used:

- `permissions` for target permission-code existence
- `role_permissions` joined through the Django relations to `roles` for permission-to-role assignment

`user_group_map` was identified from code but was not queried because user-level assignment was not necessary to answer the permission-to-role mapping question. No personal identifiers or raw IDs were selected or recorded.

## 4. Permission Code Existence

| permission code | exists? | assignment count by roles | conclusion |
|---|---:|---:|---|
| `contracts.view` | Yes | 3 | Existing and assigned read permission |
| `contracts.create` | Yes | 3 | Existing and assigned create permission |
| `contracts.edit` | No | 0 | Cannot be used until explicitly provisioned and assigned |
| `contracts.delete` | No | 0 | Cannot be used until explicitly provisioned and assigned |
| `directory.edit` | Yes | 3 | Existing and assigned employee write permission |
| `directory.view` | Yes | 4 | Existing and assigned employee read permission |

Counts represent distinct role codes linked through `role_permissions`. They do not represent user counts.

## 5. Role Assignment Summary

| permission code | role codes assigned |
|---|---|
| `contracts.view` | `manager`, `super_admin`, `tenant_admin` |
| `contracts.create` | `manager`, `super_admin`, `tenant_admin` |
| `contracts.edit` | none |
| `contracts.delete` | none |
| `directory.edit` | `manager`, `super_admin`, `tenant_admin` |
| `directory.view` | `manager`, `project_manager`, `super_admin`, `tenant_admin` |

Only role codes are recorded. No user identifiers are included.

## 6. Findings

- `contracts.edit` does not exist in the inspected central permission table.
- `contracts.edit` is not assigned to any role.
- `contracts.delete` does not exist in the inspected central permission table.
- `contracts.delete` is not assigned to any role.
- `directory.edit` exists and is assigned to three roles, providing grounded evidence for employee write authority.
- There is not enough evidence to use `contracts.edit` for contract write hardening in the current baseline because the permission row and assignments are absent.

Existing `contracts.view` and `contracts.create` assignments do not provide a safe substitute:

- `contracts.view` remains read authority.
- `contracts.create` remains creation authority.
- Neither should authorize contract update, event write, or attachment deletion.

## 7. Impact On Next Implementation

Do not implement contract write hardening with `contracts.edit` yet.

Required next step:

- plan explicit central permission provisioning as a separate approved scope
- define `contracts.edit` semantics
- create the permission row only after approval
- assign it to explicitly approved roles
- validate role/session permission loading
- only then protect contract detail POST with `contracts.edit`

After provisioning and validation:

- contract detail POST guard may use `contracts.edit`
- contract-scoped event write guard may use `contracts.edit`
- contract attachment and contract-scoped event attachment deletion may use `contracts.edit`

Do not silently create permissions or role assignments, and do not use `contracts.create` as a workaround.

## 8. Safety Notes

Confirmed:

- no code was modified
- database operations were SELECT/read-only
- no DB write was performed
- no migration was performed
- no delete endpoint was called
- no S3 access was performed
- no `.env` contents were directly inspected or printed
- Django settings loaded connection configuration silently for the approved read-only shell query
- no `RRN_SYM_KEY` was printed or changed
- no ciphertext was printed
- no decrypted personal data was printed
- no presigned URL was printed
- no UUID, object key, attachment filename, raw ID, user email, user name, or phone number was recorded
- `excel_preview.html` was not recreated
- `thumbnail-utils.js` was not created
