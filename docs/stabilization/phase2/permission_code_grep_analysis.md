# Permission Code Grep Analysis

## 1. Current Baseline

- Branch: phase2-clean-base
- Baseline commit: 14c1667 phase2: document upload get delete permission design
- Working tree expected state: clean

## 2. Permission Code Occurrence Summary

| permission code | found? | observed meaning |
|---|---:|---|
| contracts.view | Yes | contract list/detail read |
| contracts.create | Yes | contract_create GET/POST only |
| contracts.edit | Docs only | candidate only, no confirmed enforcement |
| contracts.delete | Docs only | risk/design mention only, no confirmed enforcement |
| directory.view | Yes | employee option/list/detail read |
| directory.edit | Yes | employee create/detail POST/edit UI |
| files.view | No | not confirmed |
| files.upload | No | not confirmed |
| files.delete | No | not confirmed |
| projects.view | Yes | project/scope read |
| projects.create | No | not confirmed |
| projects.edit | Yes | project create/edit/scope change |
| maps.view | Comment only | example only |
| maps.edit | Comment only | example only |

## 3. Contract Write Permission Finding

Conclusion:

- only `contracts.create` exists
- `contracts.create` is not enough to imply delete
- `contracts.edit` is not confirmed
- `contracts.delete` is not confirmed
- `files.delete` is not confirmed

Therefore contract attachment DELETE has no safe confirmed permission code yet.

Do not use `contracts.view` for DELETE.

Do not use `contracts.create` for DELETE.

Do not invent `contracts.edit` or `contracts.delete`.

## 4. File Permission Finding

`files.view`, `files.upload`, and `files.delete` were not found.

Therefore the upload helper should not depend on `files.*` permissions in the next minimal slice.

Long-term, files permission may be used as an additional AND condition, but source entity authorization must remain required.

## 5. Employee Permission Finding

Confirmed mapping:

- employee GET/read: `directory.view`
- employee DELETE/write: `directory.edit`

A limited self-GET exception is still useful for avatar/photo stability.

Recommended self-GET limits:

- same employee only
- `photo` / `photo_thumb` / `thumb` only
- no DELETE exception
- no doc/PDF/general attachment exception

## 6. Permission System Consistency

Two systems coexist:

- `gf_perm_required` using `gf_perms`
- `require_perm` using `perms` and central permission lookup

The upload helper should not invent a third permission model.

For the next minimal slice, it should use a small internal permission check that can read existing session permission values consistently.

## 7. Recommended Policy After Grep

Recommended policy:

- employee GET: `directory.view` or limited self photo GET
- employee DELETE: `directory.edit`, but not implemented in the next slice
- contract GET: `contracts.view`
- contract DELETE: defer until a real write/delete permission is confirmed
- event GET: inherit source entity read permission
- event DELETE: defer until source write policy is confirmed
- orgunit GET/delete: defer or fail closed
- project GET/delete: unsupported

## 8. Implementation Decision

Final implementation decision after grep:

- do not implement full GET+DELETE helper yet
- implement GET/read authorization first
- leave DELETE authorization for a later slice after contract write permission is confirmed

Reason:

- GET hardening reduces attachment URL exposure
- DELETE hardening without a confirmed contract write permission may break existing contract/event attachment deletion
- using `contracts.create` as DELETE permission would be incorrect

## 9. Recommended Next Code Slice

Next code slice:

- file: `geoflow_ops/views_uploads.py` only
- target: `presign_get()` only
- action: read authorization
- no `delete_attachment()` authorization change yet
- no migration
- no DB change
- preserve PDF inline
- preserve Excel download-only
- preserve avatar/photo fallback behavior

## 10. Required Smoke Tests For Next Slice

Required tests:

- employee avatar/photo_thumb GET
- employee self photo GET
- unauthorized other employee attachment GET rejected
- contract attachment GET with `contracts.view`
- event PDF inline GET
- Excel download-only behavior preserved
- normal employee detail
- damaged-RRN employee detail
- normal contract detail
- `excel_preview.html` remains absent
- `thumbnail-utils.js` remains absent

## 11. Final Recommendation

Final recommendation:

- document this grep result
- implement `presign_get` READ authorization only
- defer `delete_attachment` authorization until contract write/delete permission is confirmed
- do not use `files.*` because the codes are not confirmed
- do not use `contracts.create` for delete

