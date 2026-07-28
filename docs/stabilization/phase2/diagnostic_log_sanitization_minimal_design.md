# Diagnostic Log Sanitization Minimal Implementation Design

## 1. Baseline

- Branch: `phase2-clean-base`
- Current HEAD: `01f1bd4 phase2: analyze diagnostic log sanitization`
- Working tree expected state: clean
- `excel_preview.html`: absent
- `thumbnail-utils.js`: absent

## 2. Purpose

- Define a narrow implementation plan for sanitizing high-risk diagnostic logs.
- Remove runtime identifiers from logs without changing application behavior.
- Keep routing, permissions, upload logic, DB access, templates, static files, and migrations unchanged.
- Defer medium-risk, low-risk, static 404, and test-only cleanup items.

## 3. Scope

Only the following high-risk areas are in scope:

| area | file | reason |
|---|---|---|
| upload lifecycle diagnostics | `geoflow_ops/views_uploads.py` | may log tenant identifiers, attachment identifiers, object paths, S3-style keys, link identifiers, or user markers |
| event lifecycle diagnostics | `geoflow_ops/views_events.py` | may log tenant, event, scope, title, or record identifiers |
| contract detail diagnostics | `geoflow_ops/views_contracts.py` | may log tenant identifiers, primary keys, or detailed form errors |
| permission-denial diagnostics | `control/decorators.py` | may log user, group, or full permission-set values |
| employee RRN guard diagnostics | `geoflow_ops/views_employees.py` | may log employee identifiers during decryption guard handling |

## 4. Explicitly Out of Scope

Do not change in this minimal implementation:

- `control/views_users_admin.py` central dashboard medium-risk log
- `control/middleware.py` fixed `MW` route diagnostics
- `control/db_router.py` fixed `ROUTER` diagnostics
- `control/views_auth.py` fixed `AUTH` and `POST-LOGIN` diagnostics
- `control/tenant_connections.py` fixed tenant connection diagnostics
- test-only diagnostic output
- login icon static 404
- W342 warning
- upload behavior
- event behavior
- contract behavior
- employee RRN decrypt behavior
- permissions
- templates or static files
- `settings.py`

## 5. Sanitization Rules

A sanitized production diagnostic message must not include:

- tenant alias
- connection alias
- DB alias
- DB name
- DB host
- DB password
- group UUID
- user email
- user name
- phone number
- employee identifier
- contract UUID or primary key
- event UUID or primary key
- attachment ID
- S3 bucket
- S3 object key
- object path
- presigned URL
- raw scope ID
- raw request identifier
- decrypted RRN
- ciphertext
- full form error payload if it may include field values

Allowed message style:

- fixed outcome labels only
- fixed action labels only
- safe exception class name only if needed
- non-identifying permission codename only if needed
- no interpolated runtime identifier values

## 6. Proposed File-level Changes

### 6.1 `geoflow_ops/views_uploads.py`

Replace upload lifecycle logs that include runtime identifiers with fixed messages.

Examples of allowed direction:

- `presign-get processed`
- `presign-put request rejected`
- `upload commit processed`
- `attachment delete processed`
- `attachment authorization denied`

Do not log:

- alias
- attachment ID
- object key
- S3 key
- entity ID
- link ID
- user marker
- presigned URL

### 6.2 `geoflow_ops/views_events.py`

Replace event create, update, and delete logs that include runtime identifiers with fixed messages.

Allowed direction:

- `event create request processed`
- `event update request processed`
- `event delete request processed`
- `event validation failed`

Do not log:

- tenant alias
- event ID
- scope ID
- title
- contract ID
- employee ID
- raw request data

### 6.3 `geoflow_ops/views_contracts.py`

Replace contract detail and edit logs that include runtime identifiers with fixed messages.

Allowed direction:

- `contract detail read`
- `contract detail update request`
- `contract form validation failed`

Do not log:

- tenant alias
- contract primary key
- contract code or name
- client name
- serialized form errors containing values

### 6.4 `control/decorators.py`

Replace permission-denial logs that include runtime identifiers with fixed messages.

Allowed direction:

- `authorization denied`
- `authorization denied: missing required permission`

Do not log:

- user ID
- user email
- group ID
- role list
- full permission set
- session contents

A non-identifying permission codename may be kept only if it does not expose user-specific data.

### 6.5 `geoflow_ops/views_employees.py`

Replace RRN decryption guard logs that include employee identifiers with fixed messages.

Allowed direction:

- `employee rrn decrypt failed`
- `employee rrn decrypt failed: safe fallback used`

Do not log:

- employee ID
- employee name
- RRN value
- ciphertext
- decrypted personal data
- key material
- request user identifier

## 7. Behavior Preservation Requirements

Implementation must not change:

- HTTP status codes
- redirects
- templates rendered
- DB queries
- DB writes
- S3 operations
- presigned URL generation logic
- upload authorization logic
- read authorization logic
- delete authorization logic
- contract permission logic
- event permission logic
- employee RRN fallback behavior
- tenant routing
- central routing
- middleware behavior
- router behavior

## 8. Verification Plan

After implementation, run:

| command | purpose |
|---|---|
| `python -m py_compile geoflow_ops/views_uploads.py geoflow_ops/views_events.py geoflow_ops/views_contracts.py geoflow_ops/views_employees.py control/decorators.py` | syntax check |
| `python manage.py test geoflow_ops.test_attachment_delete_authorization` | attachment delete authorization regression |
| `python manage.py test geoflow_ops.test_upload_write_csrf` | upload write CSRF regression |
| `python manage.py test geoflow_ops.test_upload_presign_get_read_authorization` | presign GET read authorization regression |
| `python manage.py test geoflow_ops.test_contract_write_permission` | contract write permission regression |
| `python manage.py test geoflow_ops.test_event_write_permission` | event write permission regression |
| `python manage.py test control.test_group_search_login_fix` | login and group-selection regression |
| `python manage.py test control.test_tenant_connection_registration` | tenant routing and connection regression |
| `python manage.py check` | Django system check |

Expected:

- all tests pass
- existing W342 warning only
- no migration required
- no browser smoke required for this minimal log-only cleanup

## 9. Post-implementation Review

After implementation, inspect the diff manually and confirm:

- only in-scope files changed
- no behavior logic was altered
- no template, static, settings, or migration file changed
- no runtime identifiers remain in the targeted high-risk log messages
- no new logs include runtime identifiers
- no `.env` or secret values were printed
- `excel_preview.html` remains absent
- `thumbnail-utils.js` remains absent

## 10. Deferred Items

Remain deferred:

- central dashboard medium-risk log cleanup
- fixed route diagnostic level adjustment
- test-only diagnostic cleanup
- login icon static 404 cleanup
- W342 model warning cleanup
- Level 2 controlled write/upload smoke
- tenant metadata repair for non-selectable groups

## 11. Safety Notes

- No code was modified by this design task.
- No DB write was performed.
- No migration was performed.
- No endpoint was called.
- No browser smoke was performed.
- No S3 access was performed.
- No presigned URL was generated.
- No `.env` contents were printed.
- No `RRN_SYM_KEY` was printed or changed.
- No ciphertext or decrypted personal data was printed.
- No actual user email, group name, group UUID, tenant alias, connection alias, DB host, DB password, DB configuration value, contract UUID, event UUID, attachment ID, S3 key, presigned URL, or raw identifier was recorded.
- `excel_preview.html` was not recreated.
- `thumbnail-utils.js` was not created.
