# Upload Authorization Read-only Analysis

## 1. Current Baseline

- Branch: phase2-clean-base
- Baseline commit: bf3d53e phase2: record checkpoint after excel download-only cleanup
- Working tree expected state: clean
- Excel preview policy: disabled / download-only
- Orgunit attachment status: deferred

## 2. Upload API Inventory

Current upload-related endpoints:

| Endpoint | Function | Method | CSRF status | Current auth check | Risk |
|---|---|---:|---|---|---|
| /api/uploads/presign-put/ | presign_put | POST | csrf_exempt | login_required only | High |
| /api/uploads/commit/ | commit | POST | csrf_exempt | login_required only | Very high |
| /api/uploads/presign-get/<id>/ | presign_get | GET | not applicable | login_required only | High |
| /api/uploads/delete/<id>/ | delete_attachment | DELETE | csrf_exempt | login_required only | Very high |

Tenant alias handling reduces cross-tenant DB exposure, but it does not provide same-tenant entity-level authorization.

## 3. Entity-level Authorization Gaps

Current APIs do not sufficiently verify:

- whether the requested entity exists
- whether the user can view the entity
- whether the user can edit or attach files to the entity
- whether the purpose is allowed for the entity type
- whether MIME type and extension match the allowed purpose
- whether the object key belongs to the current tenant/entity/purpose prefix
- whether commit payload matches a previously issued presign-put intent

Entity-specific gaps:

- event: existence and scope authorization are incomplete
- employee: existence, self-edit, and directory permission checks are incomplete
- orgunit: existence and view/edit permission checks are missing
- contract: existence and contract permission checks are missing
- project: currently not explicitly supported by upload API

## 4. Attachment-level Authorization Gaps

presign_get() and delete_attachment() currently look up attachments by attachment ID in the current tenant DB.

Potential issue:

- a logged-in user in the same tenant may access or delete an attachment if they know its UUID

Missing checks:

- attachment entity type
- source entity existence
- user view permission for GET
- user edit/delete permission for DELETE
- event attachment link authorization
- employee attachment self/manager/admin policy
- orgunit/contract/project scope policy

GET and DELETE should use different permission levels:

- GET should require entity view permission
- upload, commit, and delete should require entity edit or attachment-management permission

## 5. CSRF Risk

The following write endpoints still use csrf_exempt:

- presign_put
- commit
- delete_attachment

Risk:

- session-cookie authentication combined with csrf_exempt may allow unintended write operations
- presigned PUT issuance, attachment metadata creation, and soft delete are affected

Observation:

- existing upload-utils.js and process-events-ui.js already send X-CSRFToken
- therefore csrf_exempt removal may be feasible after explicit testing

## 6. Orgunit Attachment Implications

Orgunit attachment UI should remain deferred until upload authorization is hardened.

Without hardening, orgunit attachment UI may allow:

- presign-put for arbitrary orgunit UUIDs
- attachment metadata creation for nonexistent orgunits
- GET of other orgunit attachments inside the same tenant
- soft delete of other orgunit attachments
- arbitrary purpose values
- same-purpose attachment accumulation
- mismatch between object_key and attachment metadata entity

Minimum policy needed before orgunit attachment:

- orgunit view permission
- orgunit edit or attachment-manage permission
- MyOrgUnit existence check
- purpose allowlist: logo, photo, doc, and possible thumbnail purposes
- MIME/extension policy per purpose
- same-purpose replacement or active-record policy
- parent/thumbnail validation policy

## 7. Minimal Hardening Plan

Do not implement this yet. Proposed future hardening plan:

### 7.1 Entity resolver

Add a centralized resolver that:

- validates entity_type
- resolves the entity in the current tenant DB
- returns 404 for nonexistent entities
- maps entity type to permission policy

### 7.2 Permission helper

Add action-aware checks:

- read: presign_get
- write: presign_put, commit, delete_attachment

Potential mapping:

- employee: directory.view / directory.edit or self exception
- contract: contracts.view / approved edit permission
- project: projects.view / projects.edit if later supported
- orgunit: explicit approved orgunit permission policy
- event: resolve event scope and inherit source entity permission

### 7.3 presign_put hardening

Add:

- entity existence check
- write permission check
- purpose allowlist
- MIME/extension/size policy
- event scope validation
- server-generated object key only

### 7.4 commit hardening

Add:

- entity allowlist
- entity existence and write permission recheck
- object key prefix validation
- event relation validation
- parent attachment validation
- transaction.atomic(using=alias) around attachment and event link creation

### 7.5 presign_get hardening

Add:

- attachment entity resolution
- read permission check
- event attachment link verification
- policy-consistent 403 or 404 response

### 7.6 delete_attachment hardening

Add:

- attachment entity resolution
- write/delete permission check
- thumbnail/parent deletion policy
- event link impact review

### 7.7 CSRF restoration

Future scope:

- remove csrf_exempt from presign_put, commit, and delete_attachment
- rely on existing X-CSRFToken behavior in frontend helpers
- smoke test CSRF success and failure cases

## 8. DB / Migration Impact

Minimum hardening can likely be implemented without new migrations.

No schema change is required for:

- entity existence checks
- attachment entity validation
- event attachment link validation
- permission checks using existing session permissions
- object key prefix validation

Possible future DB changes only if the project later adds:

- upload grants
- attachment ACL table
- audit log table
- per-object permission model

## 9. Decision

Status:

- Deferred

Reason:

- upload API hardening is necessary but high impact
- orgunit attachment should not proceed before hardening
- permission policy must be approved first
- CSRF restoration requires separate testing

Decision:

- Do not implement orgunit attachment now.
- Do not modify views_uploads.py now.
- Treat upload authorization hardening as the next candidate implementation scope, but only after explicit approval.

## 10. Recommended Next Scope

Recommended next implementation scope:

- views_uploads.py-centered authorization hardening

Suggested first implementation slice:

- entity type allowlist unification
- object key prefix validation
- attachment GET/delete entity resolution
- Excel download-only behavior must remain unchanged
- no migration or DB schema change

Required smoke tests later:

- allowed user upload/get/delete success
- view-only user upload/delete rejection
- unauthorized entity GET rejection
- nonexistent entity commit rejection
- mismatched object_key commit rejection
- CSRF-missing write request rejection
- event scope authorization

## 11. Final Recommendation

Do not implement orgunit attachment yet.

The next safest technical direction is upload authorization hardening, but it must be started as a new explicitly approved code-change scope.
