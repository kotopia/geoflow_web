# Multi-tenant group_search Login Fix Design

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 533c409 phase2: analyze group search login issue
- Working tree expected state: clean

## 2. Purpose

- Multi-tenant login currently fails during URL reversing.
- The existing group search view, URL, and template are already present.
- The immediate problem is an unqualified redirect target.
- The complete selection flow also requires redirect and session-state validation.
- This document designs only a minimal future fix.
- No code or database change is performed in this task.

## 3. Confirmed Static Findings

- `login_view()` uses `redirect("group_search")`.
- The existing registered route is namespaced as `control:group_search`.
- `group_search_view()` exists.
- `group_search.html` exists.
- `group_select_view()` exists.
- `group_search.html` links to `control:group_select`.
- `group_select_view()` appears to redirect to an unregistered or stale post-login name.
- The registered project-level post-login route is `after_login`.
- The selection path must complete tenant alias session state before entering the tenant flow.
- No user identifier, group identifier, alias, candidate list, UUID, or raw identifier is recorded here.

## 4. Fix Scope

A future code fix should be limited to:

- `control/views_auth.py`
- `control/views_groups.py`
- One DB-free test file, if possible

No template change should be included unless static inspection proves that the template contains an invalid URL name.

No migration, schema change, tenant database write, or permission provisioning is needed.

## 5. Proposed Minimal Fix

### Step 1: Initial multi-tenant redirect

Change:

- `redirect("group_search")`

To:

- `redirect("control:group_search")`

Expected effect:

- Multi-tenant login reaches the existing group selection page.
- The immediate `NoReverseMatch` is removed.

### Step 2: Selection redirect

Change the stale final redirect in `group_select_view()` to the registered post-login route.

Preferred target:

- `redirect("after_login")`

Rationale:

- The project-level post-login route already exists.
- The single-tenant flow already uses the post-login routing concept.
- This avoids inventing a new route.

### Step 3: Tenant session completion

Ensure that selecting an authorized group produces the same tenant session state expected by `/after-login/`.

Required session state must be derived from the existing single-tenant branch behavior rather than invented.

The selected group must resolve to the correct tenant database alias before redirecting to `after_login`.

### Step 4: Candidate validation

The selected group must be validated against the multi-tenant candidate list stored during login.

Rules:

- The selected group must be one of the authenticated user's candidates.
- Invalid selection must fail safely.
- Central/default database routing must remain active until the tenant alias is selected.
- No tenant database write should occur during selection.

## 6. Non-goals

- Do not redesign the UI.
- Do not add new multi-tenant tables.
- Do not change permissions.
- Do not change contracts, events, or uploads.
- Do not alter single-tenant login behavior.
- Do not create or assign `contracts.delete`.
- Do not touch the tenant schema.

## 7. Proposed Test Plan

Use DB-free or mocked tests where possible.

1. The single-tenant login branch continues to redirect through the existing post-login flow.
2. The multi-tenant login branch redirects to `control:group_search`.
3. `control:group_search` resolves successfully.
4. Group selection rejects a group not present in the stored candidate list.
5. Valid group selection stores the required selected group and session state.
6. Valid group selection stores or resolves the tenant alias consistently with the single-tenant branch.
7. Group selection redirects to the registered `after_login` route.
8. No tenant database write is performed during group selection.
9. No unresolved URL names remain in the login and group-selection flow.

## 8. Browser Smoke Plan After Implementation

Only after implementation and commit, with explicit approval:

- Log out.
- Log in as a known multi-tenant user.
- Confirm that the group selection page loads instead of raising `NoReverseMatch`.
- Select one authorized group.
- Confirm that the redirect reaches the tenant home.
- Confirm separately that normal single-tenant login still works.
- Do not record user email, group identifiers, tenant alias candidates, UUIDs, or raw identifiers.

## 9. Risk Analysis

- Fixing only the first redirect may expose the second stale redirect.
- Setting incomplete session state may route the request to the default or wrong tenant.
- Failing to validate candidate selection could allow unauthorized tenant switching.
- Changing route names globally could affect existing control URLs.
- Single-tenant login must remain unchanged.
- Browser smoke requires a suitable multi-tenant account and must be separately approved.

## 10. Out of Scope

- Actual code fixes.
- Database migrations.
- Database writes.
- Tenant provisioning.
- Permission provisioning.
- Attachment or upload authorization.
- Contract or event workflow changes.
- UI redesign.
- S3 cleanup.
- Secret or personally identifiable information inspection.

## 11. Safety Notes

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
