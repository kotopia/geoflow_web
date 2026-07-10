# Phase 0 Security Check Result

## 1. 점검일
- 2026-07-09

## 2. 현재 판단: Phase 0 보안 차단 필요
- 현재 상태는 배포/기능 확장 전 보안 차단 조치가 필요한 상태로 판단한다.

## 3. 치명 위험 목록
- settings.py SECRET_KEY 하드코딩
- DEBUG=True
- DATABASES 접속정보 하드코딩
- .env에 AWS 실제 키 존재
- RRN_SYM_KEY 하드코딩

## 4. 높은 위험 목록
- csrf_exempt 사용 함수 목록
  - control.views_auth_api.api_login
  - geoflow_ops.views_events.create_event
  - geoflow_ops.views_events.update_event
  - geoflow_ops.views_events.delete_event
  - geoflow_ops.views_uploads.presign_put
  - geoflow_ops.views_uploads.commit
  - geoflow_ops.views_uploads.delete_attachment
- migrate_all_tenants.py가 active tenant alias 전체에 migrate 수행
- tenant_provision.py에서 db_alias 기준 migrate 호출
- 0010 migration에 DROP COLUMN / DROP VIEW 포함

## 5. 중간/낮은 위험 목록
- .gitignore에 backups, *.dump, *.sql 미포함
- geoflow_ops.apps.label = webgisapp

## 6. Phase 0에서 절대 하지 않을 작업
- geoflow_ops app label 변경
- cheonan_db migration 실행
- migrate_all_tenants 실행
- tenant_provision을 cheonan_db 대상으로 실행
- DB 구조 변경

## 7. 다음 조치 순서
- cheonan_db 백업
- settings.py 환경변수화
- .gitignore 보완
- credential rotation 여부 결정
- csrf_exempt API 보완은 Phase 3로 넘김

## 8. Phase 0 진행 상태
- 현재 상태: cheonan_db 백업, .gitignore 보완, settings.py 환경변수화 완료
- Phase 0 완료 여부: 미완료
- 다음 작업: credential rotation 여부 확정 및 적용 계획 수립
- 코드 수정 여부: .gitignore, settings.py, .env, .env.example 수정 완료
- DJANGO_SECRET_KEY 교체 완료
- AWS key 교체 완료
- webgis 전용 IAM User key를 .env에 반영
- .env에만 반영
- Git에는 실제 키 미포함
- S3 업로드 테스트 성공
- S3 미리보기 테스트 성공
- 검증: py_compile 성공, manage.py check 성공
- 기존 AWS key는 Phase 0에서 비활성화/삭제하지 않음
- DB password 사용 범위 점검 완료
- DB password는 교체 권장이나 즉시 교체는 보류
- CENTRAL_DB_*, TENANT_DB_*, PROVISIONER_DB_*, group_db_config.db_password 정합성 확인 후 별도 유지보수 단계에서 교체
- Phase 0에서는 DB password 실제 값 변경 없음
- DB 구조 변경 여부: 없음

## 9. cheonan_db 백업 기록
- 백업 상태: 완료
- 백업 파일 경로: C:\GeoFlow\backups\db\cheonan_db_backup_20260709_1040.dump
- 백업 파일 크기: 198KB
- 백업 일시: 2026-07-09 10:40
- 백업 방식: pg_dump custom format (-Fc), --no-owner, --no-privileges
- 백업 검증 파일: C:\GeoFlow\backups\db\cheonan_db_backup_20260709_1040_list.txt
- 백업 목록 검증 상태: 완료
- 백업 목록 파일 생성 확인: 완료
- 복원 테스트 여부: 미실시
- 비고: cheonan_db 실제 업무 데이터 보호를 위한 Phase 0 최초 백업

## 10. Credential Rotation 판단표
| Credential | 교체 필요 여부 | 이유 | 완료 여부 |
|---|---|---|---|
| DB password | 권장 | settings.py 하드코딩은 제거됐으나 기존 password 노출 가능성이 있어 교체 권장. 단, central/tenant/provisioner/group_db_config 영향으로 별도 유지보수 단계 필요 | 조건부 보류 |
| AWS key | 완료 | webgis 전용 IAM User key로 교체 및 S3 테스트 성공 | 완료 |
| DJANGO_SECRET_KEY | 완료 | settings.py에 하드코딩되어 있었고 새 키로 교체 완료 | 완료 |
| RRN_SYM_KEY | 보류 | 실제 주민등록번호 암복호화에 사용 중 | Phase 0 교체 금지 |

## 11. .gitignore 보완 기록
- 보완 상태: 완료
- 추가 항목:
  - backups/
  - *.dump
  - *.sql
- 기존 존재 항목:
  - *.sqlite3
  - .env
  - .env.*
- 비고: 백업 파일, DB dump, SQL dump가 Git 또는 배포 패키지에 포함되지 않도록 보완함
