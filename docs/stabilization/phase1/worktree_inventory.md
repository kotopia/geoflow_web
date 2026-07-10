# Phase 1 Working Tree Inventory

## 1. 작성 목적
- Phase 0 보안 차단 1차 조치 완료 후 남아 있는 대량 working tree 변경을 분류하기 위한 문서
- 즉시 commit, restore, reset, clean을 방지하고 기능별 검토 순서를 정하기 위한 문서

## 2. 전체 요약
- Modified 개수: 47
- Deleted 개수: 4
- Untracked 개수: 58
- 위험 파일 개수: 24
- settings.py, apps.py는 현재 변경 목록에 없음
- Phase 0 관련 파일은 clean 상태

## 3. 범주별 분류

### A. control 앱 변경
- context_processors.py
- db_router.py
- decorators.py
- middleware.py
- models.py
- services 계층 변경
- templates/control/*
- urls.py
- views_auth.py
- views_groups.py
- views_groups_admin.py
- views_join.py
- views_people.py
- views_users_admin.py
- views_memberships.py
- 신규 services/acl.py, audit.py, db_alias.py, identity.py, mail.py, membership_guard.py, people.py, tenant_deprovision.py, tenant_provision.py, tenant_seed.py

### B. geoflow_ops 변경
- forms.py
- models.py
- urls.py
- views_catalog.py
- views_contracts.py
- views_employees.py
- views_myinfo.py
- views_projects.py
- context_processors.py
- templates/geoflow_ops/*
- static/geoflow_ops/js/*

### C. S3 upload / attachment / event 변경
- geoflow_ops/services/s3_service.py
- geoflow_ops/views_uploads.py
- geoflow_ops/views_events.py
- geoflow_ops/static/geoflow_ops/js/upload-utils.js
- geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js
- geoflow_ops/static/geoflow_ops/js/process-events-ui.js
- geoflow_ops/templates/geoflow_ops/events/
- geoflow_ops/templates/geoflow_ops/excel_preview.html
- geoflow_ops/migrations/0015_attachment.py
- geoflow_ops/migrations/0016_add_attachment_soft_delete.py
- geoflow_ops/migrations/0017_attachment_kind_attachment_parent.py
- geoflow_ops/migrations/0018_processevent_processeventattachment.py

### D. migration / DB 구조 위험 변경
- control/migrations/0002_tenant_deprovision_and_audit.py
- control/migrations/0003_add_is_superadmin_flag.py
- control/migrations/0004_audit_events.py
- geoflow_ops/migrations/0006~0018
- geoflow_ops/migrations/_template_ddl_plus_schema_version_bump.py
- geoflow_ops/models.py
- control/models.py

### E. tenant provision / DB 실행 위험 변경
- control/services/tenant_provision.py
- control/services/tenant_deprovision.py
- control/services/db_alias.py
- control/db_router.py
- control/middleware.py
- manage.py
- requirements.txt
- scripts/

### F. 문서/운영/스크립트 변경
- README.md
- UPLOAD_REFACTORING_SUMMARY.md
- docs/AWS_KMS_SETUP.md
- docs/AWS_QUICK_REFERENCE.md
- docs/cheonan_db_account_migration.md
- docs/migration_guide.md
- docs/migration_troubleshooting.md
- docs/runbook_migrations.md
- docs/tenant_db_permissions.md
- docs/kms-policy-local-dev.json
- docs/kms-policy-production.json
- .github/
- scripts/

### G. 삭제된 파일
- control/services_acl.py
- control/services_identity.py
- control/services_mail.py
- control/services_people.py

### H. 신규 파일
- 신규 파일 총 58개
- 기능군, migration군, 문서군, 스크립트군으로 분리 검토 필요

## 4. 즉시 보존 후보
- S3/첨부/이벤트 기능 묶음
- 이유: 실제 업로드/미리보기 테스트가 성공했고, 파일 간 의존성이 높음
- 단, migration 포함 여부는 별도 검토 필요

## 5. 보류 후보
- DB 라우팅
- tenant_provision
- tenant_deprovision
- 대량 migration
- manage.py
- requirements.txt
- 이유: cheonan_db와 운영 DB 구조에 직접 영향 가능

## 6. 삭제/폐기 검토 후보
- geoflow_ops 하위 한글명 백업 폴더
- legacy 서비스 삭제 파일 4개
- 임시/중복 문서 또는 스크립트

## 7. 절대 지금 실행하면 안 되는 명령
- git add .
- git reset --hard
- git clean -fd
- git restore .
- python manage.py migrate
- python manage.py makemigrations
- python manage.py migrate_all_tenants
- tenant_provision 실행
- git push

## 8. 다음 검토 순서
1. S3/첨부/이벤트 기능 묶음 검토
2. migration 파일 위험도 검토
3. control 앱 권한/그룹/로그인 변경 검토
4. geoflow_ops 업무 화면 변경 검토
5. tenant provision/deprovision 계열 보류 판단
6. 삭제/임시 파일 정리 판단
