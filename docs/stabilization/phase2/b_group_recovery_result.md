# Phase 2 B Group Recovery Result

## 1. 기준 상태

- Branch: phase2-clean-base
- Latest checked commit: 38a84ee phase2: document topbar avatar smoke test
- Working tree status: clean
- Original dirty worktree: C:\GeoFlow\geoflow_web
- Clean worktree: C:\GeoFlow\geoflow_web_commitA_clean

## 2. B Group Scope

B그룹은 tenant 화면, 직원, 프로젝트, 조직/내정보, topbar UI 관련 변경 후보를 대상으로 했다.

주요 검토 파일:

- geoflow_ops/forms.py
- geoflow_ops/static/geoflow_ops/js/gf-list-core.js
- geoflow_ops/static/geoflow_ops/js/hr-list.js
- geoflow_ops/templates/geoflow_ops/base_tenant.html
- geoflow_ops/templates/geoflow_ops/employees/employee_create.html
- geoflow_ops/templates/geoflow_ops/employees/employee_list.html
- geoflow_ops/templates/geoflow_ops/employees/employee_request_role.html
- geoflow_ops/templates/geoflow_ops/myinfo/orgunit_detail.html
- geoflow_ops/templates/geoflow_ops/myinfo/orgunit_form.html
- geoflow_ops/templates/geoflow_ops/partials/topbar.html
- geoflow_ops/views_catalog.py
- geoflow_ops/views_myinfo.py
- geoflow_ops/views_projects.py

## 3. Implemented Changes

### 3.1 Employee list empty state

Commit:

- 0ec5b8d phase2: improve employee list empty state

Files:

- geoflow_ops/templates/geoflow_ops/employees/employee_list.html
- geoflow_ops/static/geoflow_ops/js/hr-list.js
- geoflow_ops/static/geoflow_ops/js/gf-list-core.js

Result:

- table-responsive wrapper corrected
- empty row removed from template
- DataTables emptyTable option added
- employee empty-state text handled in JavaScript

Validation:

- git diff --check passed
- python manage.py check passed with existing W342 warning only

### 3.2 Partner label and role request selection

Commit:

- 0df6da7 phase2: improve partner labels and role request selection

Files:

- geoflow_ops/forms.py
- geoflow_ops/views_employees.py
- geoflow_ops/templates/geoflow_ops/employees/employee_request_role.html

Result:

- ContractForm partner select labels now show name plus type/kind when available
- employee role request screen now receives current_role_code
- current role is selected in the role request dropdown

Validation:

- git diff --check passed
- python manage.py check passed with existing W342 warning only

### 3.3 Project scope catalog security

Commit:

- 0495dcd phase2: secure project scope catalog views

File:

- geoflow_ops/views_catalog.py

Result:

- catalog_board now uses _alias(request)
- project_scope_summary now requires login
- project_scope_summary now requires projects.view permission

Validation:

- git diff --check passed
- python manage.py check passed with existing W342 warning only

### 3.4 Codex agent rules

Commit:

- 2b2cdf2 phase2: add codex agent rules

File:

- AGENTS.md

Result:

- Codex work rules documented
- prohibited operations documented
- GeoFlow-specific DB, migration, secret, tenant, and Git rules documented

### 3.5 Topbar avatar from S3

Commit:

- ab9ab83 phase2: load topbar avatar from s3

File:

- geoflow_ops/templates/geoflow_ops/partials/topbar.html

Result:

- topbar avatar image now accepts avatar_attachment_id
- presign-get endpoint is called from JavaScript
- avatar src is replaced only when presigned_url is returned
- default avatar fallback remains intact
- existing username, Settings, orgunit link, and Logout menu are preserved

Validation:

- git diff --check passed
- python manage.py check passed with existing W342 warning only

### 3.6 Topbar avatar smoke test

Commit:

- 38a84ee phase2: document topbar avatar smoke test

File:

- docs/stabilization/phase2/topbar_avatar_smoke_test.md

Result:

- local browser smoke test documented
- /contracts/, /employees/, /projects/, /myinfo/org-units/, and employee detail/edit pages returned HTTP 200
- presign-get endpoint returned HTTP 200
- employee edit POST still worked

## 4. Deferred Changes

### 4.1 base_tenant.html global overlay cleanup

Status:

- Deferred

Reason:

- dirty change attempted global DOM cleanup
- risk of removing valid modals, overlays, offcanvas elements, and SweetAlert containers
- all tenant pages inherit base_tenant.html
- impact area is too broad

Decision:

- Do not apply dirty hunk.
- Revisit only if a specific overlay/backdrop bug is reproduced.

### 4.2 employee_create.html address fields

Status:

- Deferred

Reason:

- dirty change adds addr_zip, addr_road, addr_detail input fields
- current model/search did not confirm these fields are supported
- current create view did not confirm save handling for these fields

Decision:

- Do not add UI fields until DB columns and save logic are verified.

### 4.3 orgunit attachment feature

Status:

- Deferred as separate Phase 2C candidate

Files involved:

- geoflow_ops/templates/geoflow_ops/myinfo/orgunit_detail.html
- geoflow_ops/templates/geoflow_ops/myinfo/orgunit_form.html
- geoflow_ops/views_myinfo.py

Reason:

- dirty change adds logo/photo/document attachment behavior
- requires Attachment model, presigned URLs, thumbnail logic, and form layout changes
- too large to include in B-group small recovery

Decision:

- Treat as a separate feature branch or Phase 2C task.

### 4.4 views_projects.py cleanup

Status:

- Deferred

Reason:

- dirty diff mostly adds section comments
- project_detail_page login decorator is mostly redundant with existing permission decorator
- duplicate import cleanup has low value

Decision:

- Do not modify for now.
- Revisit only during project module cleanup.

### 4.5 Excel preview template

Status:

- Reverted / Disabled

Reason:

- Browser-rendered Excel preview cannot reliably match Excel's native layout and behavior.
- The project decision is to keep Excel attachments download-only.
- Commit 58e5c05 added the template, but commit aa2c76f reverted it.

Decision:

- Do not recreate geoflow_ops/templates/geoflow_ops/excel_preview.html.
- Keep Excel attachment behavior download-only.
- Revisit only if a later requirement accepts approximate table preview or uses a more reliable server-side/document-rendering approach.

## 5. Final B Group Decision

B그룹은 다음 기준으로 처리했다.

Implemented:

- small safe UI fixes
- permission hardening
- alias unification
- topbar avatar feature after dependency analysis and smoke test

Deferred:

- broad common-template DOM cleanup
- DB-dependent employee address fields
- orgunit attachment feature
- low-value project view cleanup

## 6. Validation Summary

Repeated validations during B-group recovery:

- git status --short checked after each task
- git diff --check passed for code changes
- python manage.py check passed with only existing W342 warning
- local browser smoke test passed for topbar avatar

Known acceptable warning:

- catalog.CategoryParent.child W342

## 7. Next Recommended Step

Close D-group helper review with:

- thumbnail-utils.js: rejected
- excel_preview.html: disabled / reverted
- UPLOAD_REFACTORING_SUMMARY.md: reference only / document only

Next implementation work should be selected from a new, explicitly approved scope.
