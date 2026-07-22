# Phase 2C Orgunit Attachment Analysis

## 1. Current Baseline

- Branch: phase2-clean-base
- Baseline commit: 1a5d9f7 phase2: record checkpoint after b and d groups
- Working tree expected state: clean
- Excel preview policy: disabled / download-only
- thumbnail-utils.js policy: rejected

## 2. Feature Summary

The dirty orgunit attachment candidate adds:

- orgunit logo upload and display
- orgunit photo upload and display
- one orgunit document upload
- PDF inline preview
- non-PDF document download
- document explicit download
- document soft delete
- S3 presigned PUT/GET usage
- tenant DB Attachment metadata lookup
- thumbnail-first display for logo/photo when matching thumbnail attachments exist

Dirty files reviewed:

- geoflow_ops/views_myinfo.py
- geoflow_ops/templates/geoflow_ops/myinfo/orgunit_detail.html
- geoflow_ops/templates/geoflow_ops/myinfo/orgunit_form.html

## 3. Clean Baseline Dependencies

Clean branch already contains many required building blocks:

- MyOrgUnit model
- Attachment model
- MyOrgUnitForm
- orgunit list/create/detail/update URLs
- upload presign-put, commit, presign-get, and delete routes
- views_uploads.py
- s3_service.py
- upload-utils.js
- Attachment-related migrations 0015, 0016, 0017
- process-event attachment migration 0018

However, file-level existence does not prove that the tenant DB schema is currently ready.

## 4. Key Risks

### 4.1 Unclear DB readiness

Attachment model and migration files exist in clean code, but this analysis did not query the DB and did not run migration commands.

Therefore, actual tenant DB readiness is not confirmed.

### 4.2 Authorization boundary

The existing upload/get/delete APIs appear to rely mainly on login and tenant alias.

Before enabling orgunit attachment UI, the project should define and enforce:

- orgunit view permission
- orgunit edit permission
- entity ownership or scope validation
- attachment access validation
- attachment delete permission

### 4.3 Dirty files should not be copied wholesale

Dirty files are too broad and mix layout changes with upload, preview, download, and delete logic.

They also duplicate logic that should preferably be handled by common upload helpers.

### 4.4 Thumbnail policy mismatch

Dirty orgunit form uses uploadSingleFile(), not uploadImageWithThumbnail().

Dirty detail view prefers {purpose}_thumb when available.

This creates a mismatch unless thumbnail creation policy is explicitly defined.

### 4.5 Same-purpose replacement policy missing

New logo/photo/doc uploads do not clearly deactivate or replace previous attachments with the same purpose.

Without a policy, attachments may accumulate.

## 5. File-by-file Assessment

### views_myinfo.py

Dirty change:

- imports Attachment and generate_presigned_get_url
- queries orgunit attachments by purpose
- selects logo/photo/document
- generates presigned URLs for logo/photo
- adds attachment context to templates

Risk:

- medium to high
- should not be copied wholesale

### orgunit_detail.html

Dirty change:

- adds logo/photo display
- adds document preview/download/delete UI
- adds direct fetch-based JavaScript

Risk:

- high
- should not be copied wholesale

### orgunit_form.html

Dirty change:

- adds edit-mode upload panels
- uses upload-utils.js
- calls uploadSingleFile() for logo/photo/doc

Risk:

- medium to high
- should not be copied wholesale

## 6. Migration / DB Impact

New migration files are not currently recommended.

However, implementation is blocked until Attachment schema readiness is safely confirmed.

Current assessment:

- migration file support appears present in code
- DB readiness is unclear
- no DB command was run during this analysis
- feature should not be implemented until readiness is confirmed

## 7. Implementation Feasibility

Assessment:

- feasible in principle with existing clean backend
- but blocked by unclear DB state and incomplete authorization policy

Minimum safe implementation would likely require:

1. DB readiness confirmation under a separately approved read-only procedure
2. orgunit attachment permission policy
3. possible views_uploads.py authorization hardening
4. minimal views_myinfo.py context additions
5. minimal orgunit_form.html upload panel
6. minimal orgunit_detail.html attachment display/download/delete panel
7. PDF inline only
8. Excel and Office files download-only

## 8. Decision

Status:

- Deferred

Reason:

- DB schema readiness is unclear
- authorization boundary is insufficiently defined
- dirty implementation is too broad
- thumbnail and replacement policies are unresolved

Decision:

- Do not implement orgunit attachment UI now.
- Do not copy dirty orgunit files wholesale.
- Revisit as a separate Phase 2C feature after DB readiness and permission policy are approved.

## 9. Additional Finding

Clean upload-utils.js still appears to contain an Excel preview route branch.

This conflicts with the current Excel download-only policy because:

- excel_preview.html was reverted
- Excel preview remains disabled
- Excel attachments should be download-only

Recommended next scope:

- read-only analysis of upload-utils.js Excel preview branch
- then, if confirmed, a one-file minimal cleanup to keep Excel attachments download-only

## 10. Final Recommendation

Do not implement orgunit attachment yet.

Next safest implementation candidate:

- clean up upload-utils.js Excel preview leftover behavior, if confirmed by a read-only check
