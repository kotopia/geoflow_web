# Group Selection Selectable Candidate Filtering Design

## 1. Baseline

- Branch: phase2-clean-base
- Baseline commit: 4ec4718 phase2: document selectable tenant candidate diagnosis
- Working tree expected state: clean

## 2. Problem Summary

- Multi-membership users can currently see tenant candidates that are not actually connectable.
- Read-only diagnosis showed that only one candidate per tested multi-membership account fully passed metadata requirements.
- Other candidates failed because of inactive membership, missing group DB config, missing required user metadata, missing required password metadata, or combined metadata failures.
- The connection helper correctly fails closed.
- The UX problem is that non-selectable candidates are offered as selectable choices.

No actual user, group, tenant, connection, UUID, alias, database, or raw identifier is recorded.

## 3. Design Principle

- The group selection page must show only candidates that can pass the helper's metadata preconditions.
- Session `tenant_candidates` must contain only selectable candidates.
- `group_select` fail-closed validation must remain unchanged.
- The connection helper must remain strict.
- Missing or incomplete DB configuration must not be hidden by falling back to static `settings.py` aliases.
- Do not add environment-specific aliases statically to `settings.py`.
- Do not weaken tenant connection verification.
- Do not route tenant business models to the central database.

## 4. Selectable Candidate Definition

A selectable candidate must satisfy all of the following central metadata conditions:

1. User-group membership exists.
2. Membership is active.
3. The group is active.
4. Group DB config exists.
5. A connection alias is present.
6. A DB name is present.
7. A DB host is present.
8. A DB port is present.
9. A DB user is present.
10. DB password metadata is present.
11. The session candidate alias matches the config alias.
12. Required display fields are safe to render.

If any condition fails, the candidate must not be shown as selectable.

These checks establish metadata eligibility only. They do not validate network connectivity or credentials through a real tenant query.

## 5. Proposed Code Scope

Future implementation should be limited to:

- `control/views_auth.py`
- `control/views_groups.py`
- `control/test_group_search_login_fix.py`
- `control/test_tenant_connection_registration.py` only if shared helper behavior requires test adjustment

Avoid changes to:

- `settings.py`
- `urls.py`
- `geoflow_ops`
- templates or static assets unless the existing group-selection template requires a minimal empty-state message
- migrations
- tenant DB application code

If a template change is required, limit it to the existing group-selection template and do not create new static assets.

## 6. Proposed Implementation Direction

1. Extract or centralize candidate eligibility logic so login resolution and group-search rendering use the same selectable-candidate rule.
2. During login multi-candidate resolution, store only selectable candidates in session `tenant_candidates`.
3. During group-search rendering, display only candidates from session `tenant_candidates`.
4. Exclude inactive memberships.
5. Exclude inactive groups.
6. Exclude candidates without group DB config.
7. Exclude candidates missing a required alias, DB name, host, port, user, or password metadata.
8. Preserve existing `group_select` validation against session candidates.
9. If no selectable candidates remain, route safely to central or show a sanitized message.
10. If exactly one selectable candidate remains, keep existing behavior unless a separate design explicitly approves direct-routing changes.

### Eligibility Ownership

The preferred boundary is to apply eligibility before candidates enter session state. Rendering should consume the already filtered session list and must not become an independent authorization source.

`group_select` must continue to validate the submitted selection against the filtered session candidates. It must not trust a group identifier supplied by the URL or request alone.

## 7. Empty State Behavior

When all memberships are non-selectable:

- Do not show broken tenant choices.
- Do not expose which DB field is missing.
- Do not show an alias, host, DB name, password, UUID, or raw identifier.
- Show a generic message such as "No tenant workspace is currently available."
- Route to the central dashboard or remain on the group-selection page with a safe message.
- Record only sanitized fixed logs.

The exact central redirect versus in-page empty state should be selected during implementation based on the existing view flow. It must not cause a redirect loop.

## 8. Test Plan

DB-free mocked tests should verify:

1. Active membership, active group, and complete DB config appear as selectable.
2. Inactive membership is excluded.
3. Inactive group is excluded.
4. Missing group DB config is excluded.
5. Missing alias is excluded.
6. Missing DB name is excluded.
7. Missing host is excluded.
8. Missing port is excluded.
9. Missing user is excluded.
10. Missing password metadata is excluded.
11. Session `tenant_candidates` contains only selectable candidates.
12. The group-search page renders only session selectable candidates.
13. `group_select` still returns HTTP 403 for candidates not in session.
14. One valid candidate plus multiple invalid candidates results in only the valid candidate being offered or used according to the existing flow.
15. Zero selectable candidates receive safe central or empty-state behavior.
16. Tenant connection helper behavior remains strict.
17. `EnsureTenantAliasMiddleware` remains pass-through.
18. Existing tenant connection registration tests still pass.
19. Existing authorization, upload, contract, and event tests still pass.

Tests must use mocks and must not access a real central or tenant database.

## 9. Browser Smoke Plan After Implementation

Only after implementation and commit, with explicit approval:

- stop all development-server processes
- start one fresh `--noreload` development server from clean HEAD
- use logout or a fresh browser session
- start from `/login/`
- verify multi-membership login shows only selectable tenant candidates
- verify non-selectable groups are not shown as selectable choices
- verify selecting the visible valid candidate reaches tenant home or tenant workflow with HTTP 200
- verify `ConnectionDoesNotExist` is not observed
- verify `ImproperlyConfigured` is not observed
- verify single-tenant login still reaches tenant home with HTTP 200
- document only sanitized results

## 10. Out of Scope

- Actual code changes
- Database migration or write
- Tenant provisioning
- Static `settings.py` alias additions
- Browser smoke
- Login, group-selection, tenant workflow, event, upload, or delete endpoint calls
- S3 access or presigned URL work
- Secrets or personal-data inspection
- Fixing incomplete group DB config metadata
- Creating DB config rows for non-selectable groups

## 11. Safety Notes

- No code was modified.
- No DB write or migration was performed.
- No additional DB query was performed.
- No tenant DB access was performed.
- No endpoint was called and no browser smoke was performed.
- No S3 access or presigned URL work was performed.
- No `.env` contents, `RRN_SYM_KEY`, ciphertext, or decrypted data were printed.
- No user, group, tenant, connection, UUID, or raw identifier was recorded.
- No DB host, password, or configuration value was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
