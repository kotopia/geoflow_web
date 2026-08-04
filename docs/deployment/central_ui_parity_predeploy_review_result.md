# Central UI Parity Predeploy Review Result

## 1. Scope

- Compared the clean repository with the existing reference repository in read-only mode.
- Reviewed central URL configuration, views, templates, menu links, tenant selection, and static assets.
- Did not modify the reference repository.
- Did not execute an endpoint, browser, server, database operation, or deployment.
- No runtime identifier or sensitive value is included in this document.

## 2. Repository Context

| item | clean repository | reference repository |
|---|---|---|
| role | stabilized deployment candidate | existing dirty reference |
| branch reviewed in clean repository | `phase2-clean-base` | not used as a deployment decision source |
| central project URL configuration | present | present |
| central dashboard template | present | present |
| central sidebar menu URL set | present | present |
| tenant-selection view | stabilized candidate-bound flow | broad legacy flow |

- The project-level login and post-login routes are identical between the repositories.
- Reference-only duplicate control URL declarations do not represent missing top-level login functionality in the clean repository.

## 3. Central Dashboard Comparison

| check | result | classification |
|---|---|---|
| dashboard template content | identical | parity achieved |
| dashboard render behavior | equivalent | parity achieved |
| dashboard session diagnostic log | removed in clean repository | security improvement |
| main sidebar URL-name set | identical | parity achieved |
| central static bundle inventory | equivalent | parity achieved |

- The clean dashboard view omits the reference repository diagnostic that interpolates session-derived routing state.
- Removing that diagnostic does not remove dashboard functionality.
- The bundled CSS and JavaScript files that initially differed by hash are identical after normalizing byte-order marks, line endings, and terminal whitespace.
- No functional static bundle difference was established.

## 4. Central Layout and Menu Comparison

- The visible central sidebar URL-name set is the same in both repositories.
- The clean sidebar and topbar partials incorrectly contain document-level HTML and head markup even though they are included inside the central base body.
- The reference repository removes that duplicate document scaffolding from the partials.
- Browsers may recover from the invalid nesting, but it can cause duplicate stylesheet or script loading and inconsistent document parsing.
- This is a real central layout defect rather than a missing business feature.
- A narrow predeploy template fix should remove only the duplicated document and head blocks from the clean partials.

## 5. Global Message and Diagnostic Overlay Difference

- The reference central base includes a global message-rendering block and a large client-side UI diagnostic overlay.
- The clean central base does not include that overlay.
- The diagnostic overlay is not required for production functionality and should not be copied into the clean repository.
- The reference global message block renders message content as safe HTML, so it must not be copied without a separate output-escaping review.
- Lack of a global central message area may reduce feedback consistency for some admin actions, but it is a UX gap rather than a confirmed routing or data-function failure.
- If global messages are required, implement a small escaped alert component separately instead of recovering the reference block wholesale.

## 6. Login Comparison

| item | clean repository | reference repository | classification |
|---|---|---|---|
| login route | available | available | parity achieved |
| static icon resolution | Django static path | stale relative path | clean repository improvement |
| duplicate error presentation | removed | present | clean repository improvement |
| authentication form | present | present | parity achieved |

- The reference login template would reintroduce the previously fixed relative static icon problem.
- The clean login template should remain the deployment candidate.

## 7. Tenant Selection Comparison

| behavior | clean repository | reference repository | classification |
|---|---|---|---|
| displayed groups | session-stored selectable candidates only | broad active-group query | security-critical improvement in clean repository |
| selection authorization boundary | session candidate membership | database alias lookup after arbitrary URL selection | security-critical improvement in clean repository |
| non-selectable candidates | excluded | potentially displayed | clean repository required behavior |
| missing connection metadata | filtered or failed closed | central fallback possible | clean repository safer behavior |
| runtime identifier logging | sanitized fixed messages | dynamic identifiers logged | clean repository safer behavior |

- The clean tenant-selection difference is intentional stabilization, not missing parity.
- Recovering the reference tenant-selection behavior would reopen candidate visibility, authorization, connection, and sensitive-log risks.
- The reference client-side link-reset script is a UI workaround and is unnecessary for the stabilized session-candidate flow.
- Tenant-selection parity with the reference repository is not a deployment requirement.

## 8. Reference-only Central Function Candidates

| candidate | type | present only in reference | deployment assessment |
|---|---|---|---|
| tenant schema audit | read-oriented admin operation | yes | optional operational feature; separately review |
| tenant validation | connection or schema validation | yes | optional operational feature; separately review |
| tenant provisioning plan | operational planning | yes | intentionally deferred |
| group deactivate and restore | central metadata write | yes | functional omission if required by product scope |
| group soft delete | central metadata write | yes | functional omission if required by product scope |
| tenant detach and drop | destructive lifecycle operation | yes | intentionally prohibited for current deployment scope |
| membership deactivate | central metadata write | yes | functional omission if required by product scope |
| membership permanent delete | destructive metadata write | yes | intentionally deferred pending authorization review |
| personal group list | read-oriented self-service | yes | optional feature; not linked from the compared central sidebar |
| personal group leave | membership write | yes | optional functional omission; separately review |

- These are actual view and URL implementations rather than cosmetic buttons.
- Several perform database writes or destructive tenant lifecycle operations.
- Their absence from the clean repository is consistent with the current stabilization prohibitions.
- They must not be copied wholesale from the dirty reference repository.
- Product owners must explicitly decide whether non-destructive schema audit, tenant validation, or personal group-list functionality is required for the first deployment.

## 9. Group Administration Differences

- The reference group list displays additional deleted-state controls, tenant validation, schema audit, and provisioning-plan actions.
- The clean group list retains core group listing, creation, and editing.
- The reference group form includes stricter alias presentation rules and a destructive lifecycle danger zone.
- Missing destructive lifecycle controls do not block the current safe deployment scope.
- Alias policy and group-state presentation are meaningful validation and UX differences, but they require independent review against the current dynamic tenant connection design.
- No group administration change should be recovered without targeted tests and explicit write authorization.

## 10. User Administration Differences

- Both repositories contain user list, detail, assignment, and delete routes.
- The reference user detail adds membership deactivate and permanent-delete actions.
- The reference template also contains a diagnostic count display that should not be restored to production UI.
- Membership deactivate and delete are real write features, not simple UI parity.
- Their absence is not a blocker unless those workflows are explicitly required for the production launch.

## 11. Deployment Blocking Assessment

| finding | blocker status | reason |
|---|---|---|
| core dashboard route and content | not blocked | dashboard template and menu destinations are present |
| login and tenant selection | not blocked | clean behavior is safer and previously stabilized |
| static bundles | not blocked | normalized contents are equivalent |
| duplicated document head in sidebar and topbar partials | predeploy fix recommended | invalid included-template structure can cause inconsistent central layout behavior |
| reference-only tenant lifecycle operations | not a blocker for current safe scope | intentionally deferred and includes destructive operations |
| reference-only membership mutation | conditional product-scope gap | only blocking if required for launch operations |
| personal group self-service | conditional product-scope gap | not present in central menu and not required by current stabilized flow |
| global message presentation | non-blocking UX gap | should be reimplemented safely if required |

- Central UI parity does not require full parity with the dirty reference repository.
- The clean repository is functionally stronger in login, tenant selection, connection preparation, and sensitive logging.
- The only narrow central UI issue recommended before deployment is cleanup of document-level markup embedded in sidebar and topbar partials.
- Deployment approval should separately confirm whether tenant validation, schema audit, membership mutation, or personal group self-service is a launch requirement.

## 12. Recommended Next Action

- Prepare a minimal central partial markup cleanup design for the sidebar and topbar only.
- Do not copy the reference base diagnostic overlay or safe-HTML message rendering.
- Decide whether a small escaped global message component is required.
- Record an explicit product-scope decision for reference-only operational and membership features.
- Keep provisioning, deprovisioning, tenant drop, broad migration, and permanent membership deletion outside the deployment scope unless separately approved.
- After any approved template-only cleanup, run Django check and a controlled read-only central dashboard smoke.

## 13. Validation

| check | result |
|---|---|
| clean project URL configuration | valid |
| `python manage.py check` | passed with the existing W342 warning only |
| reference repository modified | no |
| endpoint or browser executed | no |

- The existing W342 model warning is unrelated to central UI parity.

## 14. Safety Notes

- No code, template, static file, or test was modified.
- No database write, migration, or schema operation was performed.
- No endpoint, browser, server, Git remote, or deployment was executed.
- No `.env` content was read or printed.
- No host, database value, user, password, key, token, tenant alias, group identifier, UUID, email, session value, or raw error was recorded.
- No git add, commit, pull, or push was performed.
