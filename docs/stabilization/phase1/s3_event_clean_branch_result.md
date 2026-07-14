# Phase 1 S3 Event Clean Branch Result

## 1. 기준 브랜치

- 작업 폴더: C:\GeoFlow\geoflow_web_commitA_clean
- 브랜치: phase1-s3-event-clean
- 기준 시작 commit: 502a73c phase1: document commit A temp diff review

## 2. 완료 commit

- 6b74b4a phase1: restore avatar context processor
- fbcb9cd phase1: restore topbar context processor
- 9ac75f0 phase1: wire s3 event attachments
- 9d7e484 phase1: add s3 event attachment migrations

## 3. 최종 patch 백업

- 위치: C:\GeoFlow\phase1_s3_event_clean_patches_final
- 파일:
  - 0001-phase1-restore-avatar-context-processor.patch
  - 0002-phase1-restore-topbar-context-processor.patch
  - 0003-phase1-wire-s3-event-attachments.patch
  - 0004-phase1-add-s3-event-attachment-migrations.patch

## 4. 선행 fix

### avatar_context

- settings.py에 등록된 control.context_processors.avatar_context 누락으로 /control/ 500 발생
- control/context_processors.py에 avatar_context 최소 복구
- Commit A와 분리된 별도 commit으로 처리

### topbar_user

- settings.py에 등록된 geoflow_ops.context_processors.topbar_user 누락으로 /control/ 500 발생
- geoflow_ops/context_processors.py에 topbar_user 최소 복구
- Attachment 모델 직접 import 없이 SQL + connections 방식으로 구현
- Commit A와 분리된 별도 commit으로 처리

## 5. Commit A 내용

수정 파일:
- geoflow_ops/models.py
- geoflow_ops/urls.py
- geoflow_ops/views_contracts.py
- geoflow_ops/views_employees.py
- geoflow_ops/templates/geoflow_ops/contracts/contract_detail.html
- geoflow_ops/templates/geoflow_ops/employees/employee_detail.html

주요 내용:
- Attachment 모델 추가
- ProcessEvent 모델 추가
- ProcessEventAttachment 모델 추가
- upload API route 연결
- event API/modal route 연결
- 계약 상세 이벤트 타임라인 연결
- 계약 이벤트 첨부 연결
- 직원 상세 사진/PDF 첨부 연결

## 6. Commit B 내용

추가 migration:
- geoflow_ops/migrations/0015_attachment.py
- geoflow_ops/migrations/0016_add_attachment_soft_delete.py
- geoflow_ops/migrations/0017_attachment_kind_attachment_parent.py
- geoflow_ops/migrations/0018_processevent_processeventattachment.py

주의:
- 0015 dependency는 clean branch 기준 마지막 migration인 0005_myorgunit_projectscopeitem_delete_prjcategory_and_more로 조정
- migrate는 아직 실행하지 않음
- cheonan_db 실제 DB에는 이미 테스트 중 관련 테이블/컬럼이 존재하므로, 운영 반영 전 migration 적용 전략은 별도 검토 필요

## 7. 테스트 결과

계약 상세:
- /contracts/ 목록 200
- 계약 상세 200
- upload-utils.js 200
- process-events-ui.js 200
- events list 200
- event modal 200
- event create 200
- upload presign-put 200
- upload commit 200
- event attachment link created
- event status draft → done
- event update 200
- PDF preview presign-get inline 200
- attachment delete 200
- event delete 200

직원 상세:
- /employees/ 목록 200
- 직원 상세 200
- edit=1 200
- photo presign-put 200
- photo commit 200
- photo_thumb presign-put 200
- photo_thumb commit 200
- doc presign-put 200
- doc commit 200
- doc preview inline 200
- doc download 200
- doc delete 200
- 직원 저장 후 상세 200

정적 검증:
- python -m py_compile 통과
- python manage.py check 통과
- catalog.CategoryParent.child W342 경고 1건은 기존 경고로 판단

## 8. 포트/CORS 참고

- 127.0.0.1:8010에서는 S3 direct PUT 이후 commit이 호출되지 않음
- 127.0.0.1:8000에서는 presign-put → S3 PUT → commit 흐름 정상
- 원인은 S3 CORS allowed origin에 8010이 없고 8000은 허용된 것으로 추정
- 코드 문제는 아닌 것으로 판단

## 9. 원본 main 상태

- 원본 작업 폴더: C:\GeoFlow\geoflow_web
- 브랜치: main
- main은 502a73c에 머물러 있음
- 관련 파일들이 대량 dirty 상태
- 지금 merge/cherry-pick/apply 금지
- clean branch를 기준 결과물로 보존

## 10. 다음 권장 조치

1. clean branch 결과 문서 commit
2. 원본 main dirty 상태를 별도 분석
3. 원본 main에 clean branch 4개 commit을 반영할지, 또는 clean branch를 기준 브랜치로 삼을지 결정
4. migrate는 별도 DB 적용 전략 수립 전까지 보류
5. git push는 명시 지시 전까지 보류

## 11. 금지 사항

- git push 금지
- migrate 금지
- makemigrations 금지
- 원본 main merge/cherry-pick/apply 금지
- 원본 worktree reset/restore/clean 금지
