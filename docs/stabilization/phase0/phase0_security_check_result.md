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
| DB password | 미정 | settings.py에 하드코딩 확인 | 미완료 |
| AWS key | 미정 | .env에 실제 키 존재 | 미완료 |
| DJANGO_SECRET_KEY | 필요 | settings.py에 하드코딩 확인 | 미완료 |
| RRN_SYM_KEY | 필요 | settings.py에 하드코딩 확인 | 미완료 |

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
