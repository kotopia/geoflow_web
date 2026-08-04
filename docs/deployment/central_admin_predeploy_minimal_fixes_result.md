# Central Admin Predeploy Minimal Fixes Result

## 1. Scope

- Central user-detail assignment context was aligned with the existing template contract.
- Central group list and edit displays were aligned with read-only `group_db_config` metadata.
- False editable DB Alias input behavior was removed.
- Read-only deleted-state display support was added when deletion metadata exists.
- DB-free regression tests were added.

## 2. Implemented Fixes

### User Detail Assignment

- Active group options and role options are now supplied to the user-detail template.
- Membership display context now includes the group code and membership status expected by the template.
- The existing assignment URL, permission decorator, CSRF form, and upsert behavior remain in place.
- Assignment redirects now use the existing namespaced route.

### Group Metadata Display

- The group list reads DB Alias display values directly from central `group_db_config` metadata.
- Runtime `settings.DATABASES` registration is no longer used as the group-list display fallback.
- The group edit view reads the DB Alias from central `group_db_config` metadata.
- The edit form displays DB Alias as read-only and does not submit it.
- The create form no longer presents a DB Alias input that appears to persist metadata.
- When deletion metadata is available, the group list displays a read-only deleted badge.

## 3. Explicitly Not Restored

- Danger Zone
- Schema Audit
- Validate Tenant
- Plan actions
- Membership delete or deactivate actions
- Database deletion, separation, or permanent-deletion behavior

No reference repository file was copied wholesale.

## 4. Changed Files

- `control/views_users_admin.py`
- `control/services/central_repo.py`
- `control/views_groups_admin.py`
- `control/templates/control/group_list_admin.html`
- `control/templates/control/group_form_admin.html`
- `control/test_central_admin_predeploy_fixes.py`
- `docs/deployment/central_admin_predeploy_minimal_fixes_result.md`

## 5. Validation

| validation | result |
|---|---|
| Python compilation for changed Python files | passed |
| central admin DB-free tests | 6 tests passed |
| group search and login regression tests | 16 tests passed |
| tenant connection registration regression tests | 29 tests passed |
| modified template loading | passed |
| `python manage.py check` | passed with the existing W342 warning only |
| `git diff --check` | passed |
| `excel_preview.html` | absent |
| `thumbnail-utils.js` | absent |

## 6. Safety Notes

- No database read or write was performed by the validation steps.
- No migration was created or executed.
- No endpoint or browser smoke was executed.
- No S3 operation was performed.
- No destructive central-admin feature was restored.
- No sensitive value or runtime identifier was recorded.
- No git add, commit, or push was performed.
