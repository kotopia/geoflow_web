# Topbar Avatar Smoke Test

## 1. 기준 상태

- Branch: phase2-clean-base
- Commit tested: ab9ab83 phase2: load topbar avatar from s3
- Test date: 2026-07-16
- Runtime: local Django development server
- Tenant alias observed: cheonan_db

## 2. Test Purpose

Validate that the topbar avatar feature loads an employee thumbnail/photo attachment through the existing S3 presigned GET endpoint without breaking common tenant pages.

## 3. Pages Checked

The following pages returned HTTP 200:

- /contracts/
- /employees/
- /projects/
- /
- /myinfo/org-units/
- /employees/<employee_id>/
- /employees/<employee_id>/?edit=1

Employee edit POST redirected successfully:

- POST /employees/<employee_id>/?edit=1
- Response: 302
- Follow-up detail page: 200

## 4. Avatar Presign Check

The topbar called:

- /api/uploads/presign-get/<attachment_id>/?mode=inline

Observed response:

- HTTP 200

Observed attachment purpose path:

- employees/<employee_id>/photo_thumb

This confirms that:

- avatar_attachment_id was available in template context
- topbar JavaScript called the presign endpoint
- the presign endpoint resolved the attachment from cheonan_db
- S3 presigned GET URL generation returned successfully
- default avatar fallback did not break the page

## 5. UI Regression Check

The following areas were checked manually:

- topbar remained visible
- default/static avatar loaded first
- avatar presign request completed
- tenant pages remained clickable
- employees list loaded
- employee detail loaded
- employee edit page loaded
- employee edit POST still worked
- no migration or DB schema operation was performed

## 6. Result

PASS.

The topbar avatar S3 presigned URL feature is considered smoke-tested locally.

## 7. Notes

This test does not yet verify:

- authorization granularity of presign-get beyond login and tenant DB alias
- behavior for users without avatar attachments
- expired presigned URL refresh behavior
- production S3/CORS behavior

These are separate follow-up checks.
