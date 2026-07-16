# Phase 2 Dirty File Classification

## 1. 기준 자료

분석 기준 파일:

- C:\GeoFlow\_phase1_archive\main_dirty_analysis_after_phase1_clean\10_original_tracked_only_files.txt
- C:\GeoFlow\_phase1_archive\main_dirty_analysis_after_phase1_clean\11_original_untracked_only_files.txt
- C:\GeoFlow\_phase1_archive\phase2_dirty_file_review_input.txt

수량:

- original tracked only: 44개
- original untracked only: 56개

목표:

- 원본 dirty 변경을 바로 반영하지 않고 주제별로 분류한다.
- Phase 2에서 살릴 후보와 보류/폐기 후보를 구분한다.
- 원본 main에는 merge/cherry-pick/apply 하지 않는다.

## 2. A그룹: 중앙관리/권한/멀티테넌시 core

분류:
- 고위험
- 별도 Phase 2A 검토 필요
- 즉시 반영 금지

파일:

- control/db_router.py
- control/decorators.py
- control/middleware.py
- control/models.py
- control/services/__init__.py
- control/services/central_repo.py
- control/services/emailer.py
- control/services_acl.py
- control/services_identity.py
- control/services_mail.py
- control/services_people.py
- control/templates/control/base_central.html
- control/templates/control/group_form_admin.html
- control/templates/control/group_list_admin.html
- control/templates/control/group_search.html
- control/templates/control/login.html
- control/templates/control/partials/sidebar.html
- control/templates/control/partials/topbar.html
- control/templates/control/users_detail_admin.html
- control/templatetags/acl_tags.py
- control/urls.py
- control/views_auth.py
- control/views_groups.py
- control/views_groups_admin.py
- control/views_join.py
- control/views_people.py
- control/views_users_admin.py
- control/templates/control/my_groups.html
- control/templates/control/tenant_provision_plan.html
- control/templates/control/tenant_schema_version_audit.html
- control/views_memberships.py

판단:

- 중앙 로그인, 그룹, 사용자, 권한, tenant 관리와 직접 연결된다.
- db_router/middleware/models/urls/views가 함께 섞여 있어 부분 적용 시 위험하다.
- Phase 2A에서 파일별 diff를 확인한 뒤 기능 단위로 재구성해야 한다.

## 3. B그룹: tenant 화면/직원/프로젝트 UI

분류:
- 살릴 가능성 있음
- Phase 2B 후보
- 파일별 diff 검토 후 재구성

파일:

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

판단:

- tenant UI, 직원 목록, 조직/내정보, 프로젝트 화면 관련으로 보인다.
- S3/Event clean branch의 코드와 충돌 가능성이 있으므로 전체 복사 금지.
- 우선 employee_list, hr-list, gf-list-core부터 diff 검토하는 것이 좋다.

## 4. C그룹: migration/tenant 운영/DB 관리

분류:
- 매우 고위험
- 실행 금지
- 문서 검토만 가능

파일:

- control/management/__init__.py
- control/management/commands/__init__.py
- control/management/commands/control_integrity_check.py
- control/management/commands/migrate_all_tenants.py
- control/management/commands/tenants_audit.py
- control/migrations/0002_tenant_deprovision_and_audit.py
- control/migrations/0003_add_is_superadmin_flag.py
- control/migrations/0004_audit_events.py
- geoflow_ops/migrations/_template_ddl_plus_schema_version_bump.py
- scripts/grant-tenant-permissions.ps1
- scripts/grant-tenant-permissions.sh
- scripts/smoke_employee_address_roundtrip.py

판단:

- migration과 tenant DB 운영에 직접 관련된다.
- cheonan_db에는 실제 데이터가 있으므로 구조 변경 위험이 있다.
- migrate_all_tenants 실행 금지.
- migrate/makemigrations 실행 금지.
- Phase 2에서는 읽기 전용 검토만 허용한다.

## 5. D그룹: S3/업로드/미리보기 보조 기능

분류:
- 살릴 가능성 있음
- Phase 2C 후보
- S3/Event 기능과 연결 여부 확인 필요

파일:

- UPLOAD_REFACTORING_SUMMARY.md
- geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js
- geoflow_ops/templates/geoflow_ops/excel_preview.html

판단:

- S3 direct upload, thumbnail, preview 기능과 관련 있을 수 있다.
- 현재 clean branch의 upload-utils.js, views_uploads.py, Attachment 구조와 맞는지 확인 후 적용해야 한다.

## 6. E그룹: 문서/운영 참고자료

분류:
- 보존 후보
- 코드 반영 전 문서 검토

파일:

- README.md
- .github/copilot-instructions.md
- docs/AWS_KMS_SETUP.md
- docs/AWS_QUICK_REFERENCE.md
- docs/cheonan_db_account_migration.md
- docs/kms-policy-local-dev.json
- docs/kms-policy-production.json
- docs/migration_guide.md
- docs/migration_troubleshooting.md
- docs/runbook_migrations.md
- docs/tenant_db_permissions.md
- scripts/check_geodjango.py
- scripts/cleanup_debug_users.py
- scripts/update-kms-policy-local.ps1
- scripts/update-kms-policy-local.sh

판단:

- 운영 문서로 가치가 있을 수 있다.
- KMS, migration, tenant permissions 문서는 Phase 0/1 보안 정책과 충돌 여부를 검토해야 한다.
- scripts는 실행 금지, 내용 검토만 허용한다.

## 7. F그룹: 삭제/백업/임시 파일

분류:
- 반영 금지
- archive 또는 폐기 후보

파일:

- control/delete/services_acl.py
- control/delete/services_identity.py
- control/delete/services_mail.py
- control/delete/services_people.py
- control/delete/services_tenant_provision.py
- geoflow_ops/삭제/_contract_scope_summary.html
- geoflow_ops/삭제/contract_detail.html.backup_20260129_151055
- geoflow_ops/삭제/contract_detail.html.bak
- geoflow_ops/삭제/contract_detail.html.bak2
- geoflow_ops/삭제/contract_detail_old.html

판단:

- delete 폴더와 backup/bak/old 파일은 기준 코드에 직접 반영하지 않는다.
- 필요한 내용은 별도 diff 확인 후 수동으로 재구성한다.

## 8. 기타 핵심 파일

분류:
- 고위험 또는 환경 영향 가능
- 즉시 반영 금지

파일:

- geoflow_project/asgi.py
- geoflow_project/wsgi.py
- manage.py
- requirements.txt

판단:

- 실행 환경에 영향을 줄 수 있다.
- Phase 0에서 settings/env refactor를 완료했으므로 무분별한 복구 금지.
- requirements.txt는 의존성 변경 내역만 별도 확인한다.

## 9. Phase 2 우선순위

1순위:
- B그룹 tenant 화면/직원/프로젝트 UI 중 employee_list, hr-list, gf-list-core diff 검토

2순위:
- D그룹 S3/업로드/미리보기 보조 기능 검토

3순위:
- A그룹 중앙관리/권한 core를 별도 Phase 2A로 분리 검토

4순위:
- E그룹 문서/운영 참고자료 선별 보존

보류:
- C그룹 migration/tenant 운영/DB 관리
- F그룹 삭제/백업/임시 파일
- 기타 실행 환경 파일

## 10. 금지 사항

- 원본 main merge 금지
- 원본 main cherry-pick 금지
- 원본 main patch apply 금지
- 원본 main reset/restore/clean 금지
- 원본 dirty 파일 직접 복사 금지
- git push 금지
- migrate 금지
- makemigrations 금지
- cheonan_db 구조 변경 금지
- .env 출력 금지

## 11. 다음 작업

다음 작업은 B그룹 중 아래 3개 파일의 diff를 먼저 읽기 전용으로 확인하는 것이다.

- geoflow_ops/templates/geoflow_ops/employees/employee_list.html
- geoflow_ops/static/geoflow_ops/js/hr-list.js
- geoflow_ops/static/geoflow_ops/js/gf-list-core.js
