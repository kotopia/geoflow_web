# Multi-tenant group_search Login Issue Analysis

## 1. Baseline

- Branch: phase2-clean-base
- Current HEAD: cbfa8a3 phase2: record attachment delete authorization checkpoint
- Working tree expected state: clean

## 2. Observed Symptom

- Login succeeds for a user with multiple tenant candidates.
- Post-login logic detects multiple tenant candidates.
- The code attempts to redirect to `group_search`.
- URL reversing fails because that unqualified URL name is not resolvable.
- The result is `NoReverseMatch`.
- No user identifier, tenant candidate list, group identifier, UUID, or raw identifier is recorded here.

## 3. Known Non-affected Flow

- The single-tenant login branch stores the selected tenant session state and redirects directly through the existing post-login route.
- Recent single-tenant operational smoke flows were not blocked by this issue.
- The observed failure is isolated to the multiple-tenant candidate resolution branch.

## 4. Code Findings

- `control/views_auth.py`, in `login_view()`, performs post-login tenant candidate resolution.
- When multiple candidates are found, `login_view()` stores the candidates in the session and calls `redirect("group_search")`.
- `control/urls.py` does register `group_search_view` with the route name `group_search`.
- The control URL configuration declares `app_name = "control"` and is included by the project URL configuration with the `control` namespace.
- The resolvable route name is therefore `control:group_search`, not the unqualified `group_search` used by `login_view()`.
- `control/views_groups.py` contains both `group_search_view()` and `group_select_view()`.
- `control/templates/control/group_search.html` exists and links selections through the namespaced `control:group_select` route.
- Static inspection also found a second incomplete path: `group_select_view()` redirects to the unregistered name `post_login_redirect` after selection.
- The registered project-level post-login route is named `after_login`.
- The selection view sets only group session state. It does not visibly derive and store the selected tenant database alias in that view.
- The search view queries active groups from the central database rather than visibly restricting its rows to the stored tenant candidate session list.
- These findings indicate that the initial redirect failure is a namespace mismatch, while the full multi-tenant selection flow also needs selection validation and session-routing review.

## 5. Root Cause Hypothesis

- The immediate `NoReverseMatch` is caused by a stale or unqualified redirect target: `group_search` is registered only under the `control` namespace.
- The view and template are present, so this is not simply a missing page.
- The subsequent selection path appears incomplete because it contains another stale redirect name and does not clearly complete tenant alias selection.
- This is not a database schema issue.
- This is not an attachment authorization issue.
- This is not related to `contracts.edit`.
- This is not related to upload CSRF or presign GET authorization.

## 6. Fix Options

### Option A: Register existing group selection view under `group_search`

- An additional unnamespaced route could make the current redirect resolve.
- This introduces a duplicate public route name and does not address the subsequent selection redirect or tenant session completion.
- It is therefore not the preferred option.

### Option B: Change redirect target to an existing tenant selection URL

- Change the initial redirect to the existing namespaced `control:group_search` route.
- This is the smallest and lowest-risk correction for the immediate `NoReverseMatch`.
- Before treating the complete flow as fixed, also confirm the existing selection handler validates the chosen group against the authenticated user's candidates, sets the tenant alias session state, and redirects through the registered post-login route.

### Option C: Implement minimal group selection page

- A selection view and template already exist, so creating a new page would duplicate current structures.
- This option would add unnecessary scope unless the existing selection flow is intentionally replaced.

Recommended option:

- Use Option B for the immediate namespace correction.
- Scope the future fix to the existing login and group-selection path, with focused tests for candidate validation, tenant session completion, and the final registered redirect.
- Do not implement any correction in this analysis task.

## 7. Proposed Test Plan For Future Fix

1. Confirm that single-tenant login still redirects to the tenant home.
2. Confirm that multi-tenant login redirects to the tenant/group selection page without `NoReverseMatch`.
3. Confirm that selecting an authorized candidate sets the tenant alias in the session.
4. Confirm that selection performs no tenant database write.
5. Confirm that an invalid or unauthorized group selection fails safely.
6. Confirm that central routing remains on the default database until tenant selection is complete.
7. Confirm that the final selection redirect uses a registered URL name.

DB-free tests using request/session objects and mocked central lookup services are preferred.

## 8. Out of Scope

- Actual code fixes.
- Database migrations.
- Permission provisioning.
- Tenant database mutation.
- Attachment or upload authorization.
- Event or contract workflow changes.
- UI redesign.
- Secret or personally identifiable information inspection.

## 9. Safety Notes

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
