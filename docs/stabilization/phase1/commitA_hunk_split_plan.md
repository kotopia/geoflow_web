# Phase 1 Commit A Hunk Split Plan

## 1. 판단 요약

- Commit A 목적: S3/첨부/이벤트 코드+UI 최소 묶음 commit
- 현재 상태: 기능 테스트는 통과
- 문제: 기존 수정 파일 6개에 S3/event 외 변경이 혼입
- 결론: 파일 단위 git add 금지, hunk 단위 분리 필요

## 2. 파일별 hunk 분리 필요 판단

### geoflow_ops/models.py
S3/첨부/이벤트 직접 필요:
- Attachment 모델
- ProcessEvent 모델
- ProcessEventAttachment 모델
- 첨부 soft delete 관련 필드

혼입 변경:
- Partner 문자열 표시 메서드
- MyOrgUnit 타입/컬럼 성격 변경
- EmployeeProfile 모델 대규모 추가 또는 주소 관련 변경

판정:
- hunk 분리 필요

### geoflow_ops/views_contracts.py
S3/첨부/이벤트 직접 필요:
- Attachment import
- 계약 상세 context의 계약 첨부 목록
- event modal UI 연동에 필요한 context 경로

혼입 변경:
- ContractForm 위젯 attrs 대량 변경
- 계약 생성 중복검증/IntegrityError 처리 강화
- Project 자동 생성/동기화 로직 보강
- 주석/섹션 구조 재정리

판정:
- hunk 분리 필요

### geoflow_ops/views_employees.py
S3/첨부/이벤트 직접 필요:
- Attachment import
- presigned GET URL 생성 import
- 직원 사진/썸네일 첨부 조회
- 문서 첨부 조회
- photo_url/doc_attachment context 주입

혼입 변경:
- 주소 컬럼 존재 검사 및 저장/조회 분기
- 생성/검증 흐름 변경
- 직원 삭제 view 추가
- 역할 요청 관련 whitelist/current role 노출 변경

판정:
- hunk 분리 필요

### geoflow_ops/templates/geoflow_ops/contracts/contract_detail.html
S3/첨부/이벤트 직접 필요:
- 타임라인 탭
- 이벤트 UI 영역
- eventModalMount data 속성
- process-events-ui.js, upload-utils.js 로드 및 초기화
- initAttachmentActions 연결

혼입 변경:
- 카드/탭 레이아웃 재구성
- 일부 스타일 정리

판정:
- hunk 분리 필요

### geoflow_ops/templates/geoflow_ops/employees/employee_detail.html
S3/첨부/이벤트 직접 필요:
- 직원 사진 표시 photo_url
- 사진 업로드 UI
- PDF 문서 첨부 표시/미리보기/다운로드/삭제 UI
- upload-utils.js 로드 및 업로드 스크립트 연동

혼입 변경:
- 역할 요청 버튼
- 주소 표시/입력 필드
- 중앙 권한 표시
- 삭제 버튼/동작
- 기타 화면 텍스트/구성 변경

판정:
- hunk 분리 필요

### geoflow_ops/urls.py
S3/첨부/이벤트 직접 필요:
- uploads API 라우트
- events API 라우트
- events modal UI 라우트

혼입 변경:
- employees delete 라우트 추가

판정:
- hunk 분리 필요

## 3. 신규 파일 판단

아래 신규 파일은 S3/첨부/이벤트 Commit A 후보로 보존 가능:
- geoflow_ops/services/s3_service.py
- geoflow_ops/views_uploads.py
- geoflow_ops/views_events.py
- geoflow_ops/static/geoflow_ops/js/upload-utils.js
- geoflow_ops/static/geoflow_ops/js/process-events-ui.js
- geoflow_ops/templates/geoflow_ops/events/

단, pycache 또는 빌드 산출물은 포함 금지.

## 4. migration 분리 판단

Commit A에는 migration 제외:
- geoflow_ops/migrations/0015_attachment.py
- geoflow_ops/migrations/0016_add_attachment_soft_delete.py
- geoflow_ops/migrations/0017_attachment_kind_attachment_parent.py
- geoflow_ops/migrations/0018_processevent_processeventattachment.py

이유:
- DB schema 변경은 별도 승인과 적용 타이밍 통제가 필요
- Commit B에서 별도 처리

## 5. 권장 실행 전략

1. Commit A를 바로 실행하지 않음
2. 먼저 hunk 단위로 staging 가능한지 추가 검토
3. 가능하면 git add -p 또는 patch 방식으로 S3/event hunk만 stage
4. 불가능하거나 너무 위험하면 Commit A를 보류하고 기능 묶음 전체를 별도 브랜치/별도 작업에서 재구성
5. migration 0015~0018은 계속 별도 보류

## 6. 금지 사항

- git add .
- 수정 파일 6개 전체 git add
- migration 0015~0018 동시 staging
- git restore/reset/clean
- migrate/makemigrations
- git push
