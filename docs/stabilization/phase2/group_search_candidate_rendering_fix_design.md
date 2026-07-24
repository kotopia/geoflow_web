# Multi-tenant group_search Candidate Rendering Fix Design

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 6d8ac29 phase2: document group search login smoke failure
- Working tree expected state: clean

## 2. Purpose

- The initial unqualified `group_search` URL reversing issue was fixed.
- Browser smoke reached the group selection page.
- Selecting a displayed group returned HTTP 403.
- The HTTP 403 validation must remain because it protects against unauthorized tenant selection.
- The remaining issue is that the group selection page appears to display groups outside the authorized candidates stored in the session.
- This document designs only a minimal future fix.

## 3. Current Behavior

- `login_view()` stores multi-tenant candidate information in the session.
- `group_select_view()` validates the selected group against the candidate data stored in that session.
- Invalid or non-candidate selection returns HTTP 403.
- `group_search_view()` currently renders a broader central group list rather than only the stored candidates.
- This can display central or non-candidate groups that `group_select_view()` will reject.

No actual candidate values, aliases, group identifiers, UUIDs, names, or emails are recorded.

## 4. Security Principle

- Do not loosen the HTTP 403 validation.
- Do not accept arbitrary group identifiers from the browser.
- Do not treat rendered page data as authorization.
- Session-stored candidate data remains the authorization boundary.
- The group search display must be narrowed to the same candidate set accepted by group selection.

## 5. Proposed Minimal Fix

A future implementation should:

1. Read the multi-tenant candidate list written by `login_view()` from the session in `group_search_view()`.
2. Fail safely or redirect to login in the existing style when no candidate list exists.
3. Render only the candidates in that list.
4. Avoid querying or displaying all active central groups in this flow.
5. Preserve the existing template contract where possible by mapping candidate data to the row structure expected by `group_search.html`.
6. Continue generating selection links through the existing `control:group_select` route.
7. Keep the existing `group_select_view()` validation unchanged or make it stricter.
8. Do not introduce central-group selection into this tenant-login flow.

## 6. Candidate Data Shape

- Use the same session key written by `login_view()`.
- Use the same identity field validated by `group_select_view()`.
- Do not create a second candidate representation.
- If candidate objects include a tenant alias or database key, use it only to complete session state after validated selection.
- Do not expose tenant alias candidate lists in logs or result documents.
- If display labels are needed, use only safe labels already present in the candidate structure.
- Map candidates to the existing template row shape in the view so a template change is not required.

## 7. Fix Scope

A future code fix should be limited to:

- `control/views_groups.py`
- `control/test_group_search_login_fix.py`, or one new DB-free test file if separation is useful

Avoid modifying:

- `control/views_auth.py`, unless static inspection proves that the candidate session shape requires a small correction
- Templates, unless the existing template cannot render mapped candidate rows
- `urls.py`
- `settings.py`
- Migrations
- Tenant database code

No migration, schema change, tenant database write, or permission provisioning is required.

## 8. Proposed Test Plan

DB-free or mocked tests should verify:

1. `group_search_view()` renders only candidates stored in the session.
2. `group_search_view()` does not perform the broad active-group query when candidate session data exists.
3. A central or non-candidate group is absent from the rendered context.
4. A valid rendered candidate can be selected by `group_select_view()` without HTTP 403.
5. Invalid selection still returns HTTP 403.
6. Missing candidate session data fails safely.
7. Valid group selection still redirects to `after_login`.
8. Existing single-tenant login tests remain unchanged.
9. No tenant database write occurs.

## 9. Browser Smoke Plan After Implementation

Only after implementation and commit, with explicit approval:

- Log out.
- Perform multi-tenant login.
- Confirm that the group selection page loads.
- Confirm that only authorized tenant candidates are displayed.
- Select one authorized candidate.
- Confirm that the tenant home returns HTTP 200.
- Log out.
- Perform single-tenant login.
- Confirm that the tenant home returns HTTP 200 without visiting the group selection page.

Do not record user email, group identifiers, tenant alias candidate lists, UUIDs, raw identifiers, or group names.

## 10. Risk Analysis

- Rendering broad central groups creates confusing choices that appear selectable but are forbidden.
- Loosening the HTTP 403 response would create an unauthorized tenant-switching risk.
- Mismatched candidate shapes can cause valid candidates to fail with HTTP 403.
- Template changes could expand the scope unnecessarily.
- Central group selection must remain separate from tenant selection.
- Browser smoke requires careful sanitized reporting.

## 11. Out of Scope

- Actual code fixes.
- Database migrations.
- Database writes.
- Tenant provisioning.
- Permission provisioning.
- Attachment or upload authorization.
- Contract or event workflow changes.
- Central dashboard UX redesign.
- S3 cleanup.
- Secret or personally identifiable information inspection.

## 12. Safety Notes

- No code was modified.
- No database write was performed.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated or printed.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext was printed.
- No decrypted personal data was printed.
- No user email, name, or phone number was recorded.
- No UUID, group identifier, tenant alias candidate list, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
