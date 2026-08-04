# Central Admin Predeploy Blocking Gap Review Result

## 1. Scope

- Performed a read-only code comparison between the clean repository and the existing reference repository.
- Focused only on central administration differences observed by the user.
- Classified differences as predeploy blockers, conditional launch-scope gaps, or deferred feature development.
- Did not copy any file or implementation from the reference repository.
- Did not execute an endpoint, browser, server, database operation, or deployment.

## 2. Executive Result

| area | classification | predeploy decision |
|---|---|---|
| user group and role assignment UI | functional regression | fix before deployment |
| membership deactivate button | intentionally absent write feature | defer |
| membership permanent-delete button | intentionally absent destructive feature | do not restore |
| group-list DB alias display | incorrect runtime/display coupling | fix before deployment |
| group-edit DB alias display | view-template contract defect | fix before deployment |
| group-edit DB alias mutation | unsupported but presented as editable | remove false edit affordance or design separately |
| deleted-group identification | incomplete administrative state display | minimal read-only display fix recommended before deployment |
| active/inactive badge styling | presentation-only difference | non-blocking |
| Schema Audit | reference-only operational feature | classify and defer |
| Validate Tenant | reference-only operational feature | classify and defer |
| Plan | reference-only provisioning feature | defer |
| Danger Zone | destructive lifecycle feature | prohibited; do not restore |

## 3. User Detail Group and Role Assignment Failure

### Finding

- The assignment URL and POST view exist in the clean repository.
- The clean assignment backend accepts a group identifier and role identifier and performs an upsert.
- The clean user-detail template renders selection options from context keys named `groups` and `roles`.
- The clean user-detail view does not provide either `groups` or `roles`.
- The two selection controls therefore render without usable options, so the user cannot submit a valid assignment through the UI.

### Additional Context Mismatches

- The template reads join-request rows from `joins`, while the view provides `requests`.
- The membership template expects group code and membership status fields that are not included in the view's membership dictionaries.
- These mismatches indicate that the view and template came from different recovery revisions.

### Classification

- This is a real functional regression, not a cosmetic parity difference.
- Central user-to-group role assignment is already represented as an available clean-repository feature, but its UI contract is broken.
- This is a predeploy blocking fix if central administrators are expected to assign users after launch.

### Minimal Fix Direction

- Keep the existing assignment URL, permission decorator, CSRF protection, and upsert behavior.
- Make the view and template agree on one set of context names.
- Populate only active and eligible groups and assignable roles.
- Include the membership fields actually rendered by the template.
- Align the join-request key without changing request data or authorization behavior.
- Add DB-free view/template contract tests and authorization tests.
- Do not copy the reference user-detail implementation wholesale.

## 4. Missing Membership Deactivate and Delete Buttons

### Finding

- The clean template does not contain membership deactivate or permanent-delete forms.
- The clean URL configuration and user-admin view module do not provide the corresponding endpoints.
- The reference repository provides both endpoints, buttons, confirmation flows, and database-write implementations.
- Their absence is therefore intentional or incomplete selective recovery, not a hidden template failure.

### Classification

- Membership deactivate is a separate central metadata write feature.
- Membership permanent deletion is a destructive write feature.
- Neither is required to repair the existing assignment UI.
- They are not predeploy blockers unless explicitly included in the launch product scope.
- Permanent delete must not be restored in the current deployment scope.

### Decision

- Do not add either button as part of the assignment repair.
- If membership deactivation becomes necessary, design it separately with self-protection, last-admin protection, authorization, CSRF, audit, and rollback behavior.
- Keep permanent deletion deferred.

## 5. Group-list DB Alias Display Root Cause

### Finding

- The clean group list obtains each display alias through `resolve_group_db_alias()`.
- That resolver accepts an alias from group metadata only when the alias is already present in `settings.DATABASES`.
- The stabilized application dynamically registers selectable tenant connections at runtime.
- Most dynamic tenant aliases are not statically present in `settings.DATABASES` during the central group-list request.
- The resolver therefore falls through to one shared default alias, causing multiple rows to display the same value.

### Classification

- The underlying central metadata may be distinct while the clean UI displays a shared fallback.
- This is an incorrect display caused by mixing runtime connection-registry eligibility with central metadata presentation.
- It does not prove that central metadata itself is duplicated.
- It is a predeploy administrative accuracy defect because an administrator cannot reliably identify each group's configured connection mapping.

### Minimal Fix Direction

- Read the display alias directly from the central `group_db_config` row for that group.
- Do not require the display value to be present in the current process connection registry.
- Keep runtime connection eligibility and registration checks in the tenant connection helper, not in the admin display resolver.
- Render a generic missing-state label when no configuration exists.
- Do not log or expose host, database name, database user, password, or other connection fields.
- Add DB-free tests proving that two metadata rows with different aliases remain different in rendered context without requiring static registration.

## 6. Group-edit DB Alias Display Root Cause

### Finding

- The clean edit GET query returns six group and owner fields.
- The clean template reads the DB alias from the seventh tuple position.
- The view never joins or queries `group_db_config` for the edit page.
- The expected tuple item therefore does not exist and the field cannot display the correct metadata value.
- The clean edit POST handler does not read or update the DB alias.
- The form nevertheless presents the value as an editable text field.
- The clean create handler reads a submitted alias but does not persist it to central connection metadata.

### Classification

- The edit display is a direct view-template contract defect.
- The editable field is a false affordance because saving does not change alias metadata.
- The create form has the same misleading persistence expectation.
- Correct display is a predeploy fix; alias mutation is not approved by this review.

### Minimal Fix Direction

- Load the current display alias from `group_db_config` using a read-only central query.
- Display it as read-only until a separately reviewed metadata mutation workflow exists.
- Remove or disable the false editable input in both create and edit flows if alias provisioning is not part of the launch scope.
- Do not infer a database name or credential from an alias.
- Do not update host, port, database name, user, password, alias, or group metadata in the display fix.
- Do not copy the reference upsert and provisioning behavior wholesale.

## 7. Deleted Group and Status Display Difference

### Clean Repository Behavior

- The clean group-list query returns the normal status field.
- The template renders the status as raw text.
- The query does not select a deletion timestamp or derive a deleted-state flag.
- If retained deleted rows exist, the UI cannot distinguish them from ordinary rows using deletion metadata.

### Reference Repository Behavior

- The reference list detects whether deletion metadata exists.
- It can hide deleted rows by default, include them on request, sort by lifecycle state, and render deleted and inactive badges.
- It also connects that display to restore and destructive lifecycle controls.

### Classification

- Active versus inactive badge styling is presentation-only and not a blocker.
- Failure to distinguish an existing deleted row is an administrative accuracy gap.
- A read-only deleted marker is a minimal predeploy candidate if the deployed central schema contains retained deleted rows.
- Restore, soft delete, permanent delete, detach, and drop actions are not part of that display fix.

### Minimal Fix Direction

- Detect deletion metadata without mutating schema or data.
- Return a simple deleted-state boolean or timestamp-presence flag to the template.
- Render a non-interactive deleted badge and preserve the existing raw active/inactive status.
- Do not add lifecycle action buttons.
- If the schema has no deletion metadata, preserve current behavior.

## 8. Reference-only Operational Features

| feature | reference only | feature type | current decision |
|---|---|---|---|
| Schema Audit | yes | read-oriented multi-tenant operational inspection | defer and design separately |
| Validate Tenant | yes | connection and schema validation | defer and design separately |
| Plan | yes | tenant provisioning planning | defer |
| Danger Zone | yes | deactivate, detach, drop, restore, and delete lifecycle UI | prohibited; do not restore |

- Schema Audit and Validate Tenant may be operationally useful, but the reference implementations depend on broader tenant service and lifecycle code not recovered into the clean repository.
- Plan is coupled to provisioning rules and metadata generation.
- Danger Zone includes database detach, database drop, group delete, and restore behavior.
- None should be bundled into the minimal predeploy central UI fixes.

## 9. Predeploy Minimal Fix Set

The recommended predeploy scope is limited to the following non-destructive corrections:

1. Repair the user-detail view/template context contract so group and role assignment options render and existing join and membership data use consistent keys.
2. Correct group-list alias presentation by reading central metadata without requiring static runtime registration.
3. Correct group-edit alias presentation and make it read-only.
4. Remove or disable the misleading alias input from creation when metadata creation is outside launch scope.
5. Add a read-only deleted marker when deletion metadata exists, without adding lifecycle actions.
6. Add targeted DB-free tests for context shape, rendering, permission checks, and absence of destructive actions.

## 10. Deferred Post-deployment or Separate-scope Work

- Membership deactivation workflow.
- Membership permanent deletion.
- Group deactivate, restore, soft delete, detach, or drop.
- Tenant database deletion or separation.
- Schema Audit.
- Validate Tenant.
- Tenant provisioning Plan.
- Alias or connection metadata mutation from the group form.
- Full lifecycle state-management UI.

## 11. Deployment Decision

- Deploying the clean repository without destructive reference-only tools is the safer choice.
- User group and role assignment should be fixed before deployment if central administration is part of the launch workflow.
- Incorrect alias display and false alias edit behavior should be corrected before administrators rely on the group screens.
- Deleted-state display should be corrected before deployment when retained deleted rows are present; otherwise it can remain a narrowly planned follow-up.
- Missing deactivate, delete, audit, validation, plan, and danger-zone features do not block the current stabilized tenant application deployment.
- No reference file should be copied wholesale.

## 12. Safety Notes

- No code, template, static file, or test was modified.
- The reference repository was read only and was not modified.
- No database read or write was performed.
- No migration or schema operation was performed.
- No endpoint, browser, server, Git remote, or deployment was executed.
- No host, database value, user, password, key, token, tenant alias value, group identifier, UUID, email, session value, or raw error was recorded.
- No git add, commit, pull, or push was performed.
