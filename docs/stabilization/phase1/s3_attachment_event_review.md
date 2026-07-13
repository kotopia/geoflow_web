# Phase 1 S3 Attachment Event Review

## 1. 기능 요약

포함 기능:
- presigned PUT
- upload commit
- presigned GET(inline/download)
- attachment soft delete
- event create/update/delete/list
- event attachment link
- PDF/image preview

실제 테스트 성공 항목:
- presigned PUT 성공
- upload commit 성공
- presigned GET 성공
- PDF inline preview 성공
- 오류 메시지 없음

## 2. 필수 보존 파일

- geoflow_ops/services/s3_service.py
- geoflow_ops/views_uploads.py
- geoflow_ops/views_events.py
- geoflow_ops/urls.py
- geoflow_ops/models.py
- geoflow_ops/views_contracts.py
- geoflow_ops/views_employees.py
- geoflow_ops/templates/geoflow_ops/contracts/contract_detail.html
- geoflow_ops/templates/geoflow_ops/employees/employee_detail.html
- geoflow_ops/templates/geoflow_ops/events/_event_modal.html
- geoflow_ops/static/geoflow_ops/js/upload-utils.js
- geoflow_ops/static/geoflow_ops/js/process-events-ui.js
- geoflow_ops/migrations/0015_attachment.py
- geoflow_ops/migrations/0016_add_attachment_soft_delete.py
- geoflow_ops/migrations/0017_attachment_kind_attachment_parent.py
- geoflow_ops/migrations/0018_processevent_processeventattachment.py

이유:
- URL, 모델, API, 템플릿, JS가 강결합되어 있어 일부 누락 시 presign, commit, event modal, attachment 렌더링 중 하나 이상이 깨질 수 있음.

## 3. 선택/보류 파일

- geoflow_ops/static/geoflow_ops/js/thumbnail-utils.js
- geoflow_ops/templates/geoflow_ops/base_tenant.html
- geoflow_ops/templates/geoflow_ops/partials/topbar.html
- geoflow_ops/views_myinfo.py
- geoflow_ops/templates/geoflow_ops/excel_preview.html
- geoflow_ops/views_projects.py
- geoflow_ops/forms.py

이유:
- S3/event 핵심 경로와 직접 결합이 약하거나 부가 기능 성격.
- topbar, myinfo, excel preview는 보존 가치가 있지만 핵심 최소 묶음에는 제외 가능.

## 4. migration 검토

0015:
- ops.attachments 생성
- 신규 테이블/인덱스 생성
- 파괴적 DDL 없음

0016:
- attachments에 deleted_at, deleted_by, is_deleted 추가
- soft delete 구조
- 파괴적 DDL 없음

0017:
- attachments에 kind, parent_id 추가
- 파괴적 DDL 없음

0018:
- ops.process_events, ops.process_event_attachments 생성
- unique/index 추가
- 파괴적 DDL 없음

위험 DDL 여부:
- DROP TABLE 미발견
- DROP COLUMN 미발견
- DROP VIEW 미발견
- ALTER TYPE 미발견
- RemoveField 미발견
- DeleteModel 미발견

cheonan_db 영향 판단:
- 직접 데이터 삭제/손상 리스크는 낮음
- 단, 신규 테이블/컬럼 생성은 스키마 변경이므로 적용 타이밍 통제 필요
- 코드가 Attachment/ProcessEvent 모델을 참조하므로 migration 미적용 상태에서 코드만 반영하면 기능 실패 가능성 높음

## 5. 외부 의존성

control 앱 의존 여부:
- 직접 의존은 낮음
- 현재 alias 획득과 인증/권한 흐름에 간접 의존

tenant provision 의존 여부:
- 직접 의존 없음

db_router/middleware 의존 여부:
- 간접 의존 있음
- alias 라우팅이 틀리면 첨부/이벤트가 잘못된 DB에 저장되거나 실패할 수 있음

settings.py 의존 여부:
- 코드 변경 의존은 없음
- 런타임 환경변수 의존 있음:
  - AWS_S3_BUCKET
  - AWS_ACCESS_KEY_ID
  - AWS_SECRET_ACCESS_KEY
  - AWS_REGION
  - 선택적으로 AWS_KMS_KEY_ID

## 6. 확인된 리스크

- 이벤트 생성 응답 스키마 불일치 가능성
  - 프론트는 data.event.id를 기대할 수 있음
  - 백엔드는 event_id를 반환할 수 있음
- 이벤트 생성 직후 첨부 업로드 UX 추가 테스트 필요
- soft delete 후 presign-get 410 처리 UI 반응 확인 필요
- 계약/직원/topbar 미리보기 경로 회귀 확인 필요

## 7. 권장 commit 전략

commit A:
- S3/첨부/이벤트 코드+UI 최소 묶음
- migration 제외

commit B:
- migration 0015~0018 별도
- DB 변경 승인/적용 타이밍을 코드와 분리해 통제

commit C:
- 부가 기능 별도
- topbar/avatar
- myinfo 첨부
- excel preview
- thumbnail-utils 정리

아직 commit하지 말아야 할 파일:
- control 대규모 변경군
- tenant_provision/deprovision 계열
- db_router/middleware 대규모 변경군
- S3/event와 무관한 geoflow_ops 광범위 화면 변경
- manage.py
- requirements.txt
- 기타 대량 migration

## 8. 다음 조치

1. 이벤트 생성 직후 첨부 업로드 테스트
2. 응답 스키마 불일치 여부 확인
3. 필요 시 최소 수정으로 JS/API 응답 정합성 보정
4. S3/첨부/이벤트 최소 파일 묶음 확정
5. migration 0015~0018은 별도 승인 후 처리

## 9. 아직 금지할 명령

- git add .
- git reset --hard
- git clean -fd
- git restore .
- python manage.py migrate
- python manage.py makemigrations
- python manage.py migrate_all_tenants
- tenant_provision 실행
- git push
