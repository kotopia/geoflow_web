# Central contracts.edit Permission Provisioning Design

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 8a8a70a phase2: inspect central contract permission assignments
- Working tree expected state: clean

## 2. Purpose

`contracts.edit` does not currently exist in central permission metadata. Contract write hardening cannot proceed safely until the permission is explicitly provisioned and assigned.

This document designs the provisioning process only. This task performs no DB write, code change, migration, endpoint call, or S3 action.

## 3. Current Permission State

| permission code | exists? | assigned role count |
|---|---:|---:|
| `contracts.view` | Yes | 3 |
| `contracts.create` | Yes | 3 |
| `contracts.edit` | No | 0 |
| `contracts.delete` | No | 0 |
| `directory.edit` | Yes | 3 |

Conclusion:

- `contracts.view` is read-only.
- `contracts.create` is creation-only.
- Neither may authorize update, delete, or attachment lifecycle operations.
- `contracts.edit` must be created and assigned before contract write hardening.

## 4. Proposed Permission Semantics

Proposed permission:

- code: `contracts.edit`
- meaning: update contract fields and manage contract-owned lifecycle resources

Included operations:

- contract detail POST/update
- contract-scoped event create, update, and delete
- contract attachment lifecycle operations
- contract-scoped event attachment lifecycle operations

Excluded operations:

- creating new contracts, which remains `contracts.create`
- deleting the contract record itself, which should be reserved for a future `contracts.delete` policy
- read-only contract list and detail access, which remains `contracts.view`

The proposed semantics must be approved before provisioning.

## 5. Proposed Role Assignment

Proposed initial assignments:

- `super_admin`
- `tenant_admin`
- `manager`

Do not assign initially to:

- `project_manager`
- `viewer`

Reasoning:

- `contracts.create` is currently assigned to `manager`, `super_admin`, and `tenant_admin`.
- `directory.edit` is also assigned to `manager`, `super_admin`, and `tenant_admin`.
- `directory.view` includes `project_manager`, but view access must not imply contract write authority.

This proposed role assignment requires explicit approval before any DB write.

## 6. Provisioning Method Options

Design only.

### Option A: Django shell one-time provisioning

- create `contracts.edit` only if it is missing
- assign it only to approved role codes
- use idempotent get-or-create logic
- print only permission codes, role codes, and sanitized counts
- do not query or print user identifiers
- validate the final assignment set with a separate read-only query

Advantages:

- smallest controlled local provisioning scope
- idempotent behavior can prevent duplicate rows
- immediate read-only validation is possible

Risks:

- remains an operational one-time action
- must be carefully reviewed before execution
- should not be reused informally across environments

### Option B: management command

- create a reviewed, repeatable provisioning command
- make the command idempotent
- expose a dry-run or inspection mode if practical
- restrict output to codes and counts

Advantages:

- safer for repeated environment provisioning
- auditable and testable as application code

Risks:

- requires a separate code change and review
- must not be combined with unrelated application hardening

### Option C: SQL script

- use explicit central table operations
- review constraints and conflict behavior first
- validate affected role codes before execution

Advantages:

- direct and auditable when carefully reviewed

Risks:

- higher risk if table names, constraints, or identifiers differ
- easier to make a non-idempotent or overly broad change

Recommendation:

- use Option A for a controlled local provisioning task only after explicit approval
- use Option B later if repeatable deployment provisioning is required
- avoid Option C unless the exact SQL and constraints receive separate review

## 7. Proposed Validation After Provisioning

Read-only validation after approved provisioning:

- confirm that `contracts.edit` exists
- confirm that its assigned role codes are exactly `manager`, `super_admin`, and `tenant_admin`
- confirm that `project_manager`, `viewer`, and unexpected roles do not receive it
- confirm that session permission loading includes `contracts.edit` for intended roles
- confirm that the permission is absent for non-approved roles
- print only permission codes, role codes, and counts
- do not print user identifiers or raw IDs

Session cache considerations:

- existing sessions may retain previously loaded permission sets
- logout/login or an approved session refresh may be required before runtime testing
- validation should distinguish central assignment correctness from stale session state

## 8. Follow-up Application Hardening Order

After provisioning and validation:

1. protect contract detail POST/update with `contracts.edit`
2. protect contract-scoped event create, update, and delete with `contracts.edit`
3. protect contract attachment and contract-scoped event attachment deletion with `contracts.edit`
4. run allowed-user and restricted-user smoke tests
5. record a new checkpoint document

Each application change should remain a separate, limited, reviewed slice.

## 9. Risk Analysis

- Provisioning grants new write authority and requires explicit approval.
- Assigning the permission to too many roles may broaden contract mutation rights.
- Assigning it to too few roles may break existing workflows after write guards are enabled.
- Existing role/session permission caches may require logout/login or session refresh.
- Provisioning must not be mixed with application-code hardening in one unreviewed step.
- The exact role list must be reviewed before execution.
- `contracts.delete` must not be created unless contract-record deletion policy is separately approved.

## 10. Explicit Approval Required

- No DB write should occur from this design task.
- Creating `contracts.edit` requires explicit approval.
- Assigning `contracts.edit` to any role requires explicit approval.
- The exact approved role-code list must be confirmed before execution.
- Creating `contracts.delete` is out of scope.
- Assigning `contracts.delete` is out of scope.
- Application hardening is out of scope until provisioning and validation are complete.

## 11. Safety Notes

Confirmed:

- no code was modified
- no DB write was performed
- no migration was performed
- no delete endpoint was called
- no S3 access was performed
- no `.env` was read or printed
- no `RRN_SYM_KEY` was read, printed, or changed
- no ciphertext was printed
- no decrypted personal data was printed
- no presigned URL was printed
- no UUID, object key, attachment filename, or raw ID was recorded
- no user email, name, or phone number was recorded
- `contracts.edit` was not created
- no role assignment was changed
- `excel_preview.html` was not recreated
- `thumbnail-utils.js` was not created
