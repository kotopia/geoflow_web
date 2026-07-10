# Credential Rotation Decision (Phase 0)

## 1. 현재 상태
- Phase 0 settings.py 환경변수화 commit 완료
- commit hash: c4f21e9
- .env는 Git에 포함하지 않음
- push는 아직 하지 않음

## 2. Credential별 판단표

| Credential | 현재 위험 근거 | 교체 필요 여부 | 즉시 교체 가능 여부 | 주의사항 |
|---|---|---|---|---|
| DJANGO_SECRET_KEY | settings.py에 하드코딩되어 있었음 | 완료 | 완료 | 새 키로 교체 완료, 기존 로그인 세션은 무효화될 수 있음 |
| AWS key | .env에 실제 값 존재 및 S3 presigned URL 생성에 사용 중 | 완료 | 완료 | webgis 전용 IAM User key로 교체 완료, 업로드/미리보기 테스트 성공 |
| DB password | settings.py에 하드코딩되어 있었음 | 권장 | 조건부 보류 | CENTRAL_DB_*, TENANT_DB_*, PROVISIONER_DB_*, group_db_config.db_password 정합성 확인 후 별도 유지보수 단계에서 교체 |
| RRN_SYM_KEY | settings.py에 하드코딩되어 있었고 실제 주민등록번호 암복호화에 사용 중 | 보류 | 즉시 교체 금지 | 기존 rrn_cipher 복호화 불가 위험 |

## 3. RRN_SYM_KEY 특별 주의
- 이 키가 실제 개인정보 암호화에 사용 중인지 확인 필요
- 이미 암호화된 데이터가 있다면 단순 교체 금지
- 교체하려면 기존 데이터 복호화 -> 새 키로 재암호화 절차 필요
- 아직 실제 암호화 데이터가 없다면 새 키로 교체 가능

## 4. 권장 순서
- DJANGO_SECRET_KEY 새 값 생성 및 .env 반영 완료
- AWS key는 webgis 전용 IAM User key로 교체 완료
- DB password는 교체 권장이나 Phase 0에서는 조건부 보류
- RRN_SYM_KEY는 Phase 0에서 교체하지 않음

## 5. 아직 하지 않을 것
- DB password 실제 교체
- RRN_SYM_KEY 실제 교체
- DB password / RRN_SYM_KEY의 .env 값 변경
- 기존 AWS key 비활성화/삭제
- git push
- migrate 실행

## 6. 다음 작업
- DB password 교체는 Phase 0에서 즉시 실행하지 않고, 별도 유지보수 단계에서 수행
- DB password 교체 전 중앙 DB/테넌트 DB/PROVISIONER/group_db_config 정합성 확인 필요
- RRN_SYM_KEY는 Phase 0에서 교체하지 않고 유지
- 기존 AWS key 정리 여부는 별도 단계에서 판단
- git push는 아직 하지 않음

## 7. RRN_SYM_KEY 사용 여부 확인 결과

- 확인 결과: 실제 사용 중
- 사용 위치:
	- geoflow_ops/views_employees.py
	- geoflow_ops/models.py
	- geoflow_ops/migrations/0008_create_hr_tables_if_missing.py
	- baseline_ctr_prj_hr_ops.sql
- 사용 방식:
	- pgp_sym_encrypt로 rrn_cipher 저장
	- pgp_sym_decrypt로 rrn_cipher 복호화 조회
	- rrn_hash, rrn_last4 보조 저장
- 관련 DB 필드:
	- rrn_cipher
	- rrn_hash
	- rrn_last4

## 8. RRN_SYM_KEY 최종 판단

- 판단: Phase 0에서 교체 금지
- 이유: 기존 암호화 데이터가 존재할 가능성이 있으며, 키를 단순 교체하면 기존 rrn_cipher 복호화가 불가능해질 수 있음
- 조치: 현재 값 유지
- 향후 교체 조건:
	1. rrn_cipher 실제 데이터 존재 여부 확인
	2. 기존 데이터 복호화 가능성 확인
	3. 새 키 생성
	4. 기존 데이터 복호화 후 새 키로 재암호화
	5. 백업 및 복원 테스트 완료 후 교체

## 9. AWS key 사용 여부 확인 결과

- 확인 결과: 실제 사용 중
- 사용 위치:
	- geoflow_ops/services/s3_service.py
	- geoflow_ops/views_uploads.py
	- geoflow_ops/views_employees.py
	- geoflow_ops/views_myinfo.py
- 사용 환경변수:
	- AWS_ACCESS_KEY_ID
	- AWS_SECRET_ACCESS_KEY
	- AWS_REGION
	- AWS_S3_BUCKET
	- AWS_KMS_KEY_ID
- 현재 코드에서 사용하지 않는 이름:
	- AWS_STORAGE_BUCKET_NAME
	- AWS_S3_REGION_NAME
- 사용 방식:
	- presigned PUT URL 생성
	- presigned GET URL 생성
	- 브라우저가 S3에 직접 업로드
	- 다운로드/미리보기용 presigned URL 생성
- 삭제 방식:
	- 현재 코드 기준 S3 delete_object 호출 없음
	- Attachment DB 메타데이터 소프트 삭제 중심

## 10. AWS key 최종 판단

- 판단: Phase 0 교체 완료
- 교체 방식: webgis 전용 IAM User의 새 Access Key를 .env에 반영
- 코드 수정 필요 여부: 없음
- S3 기능 테스트:
	- presigned PUT 성공
	- upload commit 성공
	- presigned GET 성공
	- PDF inline preview 성공
	- 오류 메시지 없음
- 기존 IAM User의 Access Key 2개는 Phase 0에서 비활성화/삭제하지 않음
- 기존 webgis key 정리 여부는 별도 단계에서 판단

## 11. webgis 전용 IAM User 권한 초안

- 생성 목적:
	- 기존 QGIS, boto3, 기타 S3 업로드용 Access Key와 webgis용 Access Key를 분리
- 기존 키 처리:
	- 기존 IAM User의 Access Key 2개는 Phase 0에서 비활성화/삭제하지 않음
- 현재 KMS 상태:
	- AWS_KMS_KEY_ID가 실제 값으로 설정되어 있지 않으므로 Phase 0에서는 KMS 권한 제외 가능
- 최소 S3 권한:
	- s3:PutObject
	- s3:GetObject
- 권한 범위:
	- 특정 S3 버킷의 tenants/* prefix로 제한 권장
- 현재 코드 기준 불필요 권한:
	- s3:ListBucket
	- s3:DeleteObject
	- s3:PutObjectAcl
- KMS를 나중에 사용할 경우 추가 검토:
	- kms:GenerateDataKey
	- kms:Decrypt
	- KMS Key Policy 반영 필요

## 12. DB password 사용 범위 점검 결과

- settings.py 사용 환경변수:
	- default alias: CENTRAL_DB_NAME, CENTRAL_DB_USER, CENTRAL_DB_PASSWORD, CENTRAL_DB_HOST, CENTRAL_DB_PORT
	- cheonan_db alias: TENANT_DB_NAME, TENANT_DB_USER, TENANT_DB_PASSWORD, TENANT_DB_HOST, TENANT_DB_PORT
	- cheonan_db USER/PASSWORD/HOST/PORT는 TENANT_DB_* -> PROVISIONER_DB_* -> CENTRAL_DB_* 순으로 fallback 가능
- .env 상태:
	- CENTRAL_DB_* 존재
	- TENANT_DB_* 존재
	- 실제 값은 문서에 기록하지 않음
- 하드코딩 잔존 여부:
	- 파이썬 코드 기준 DB 접속 password 리터럴 하드코딩 미발견
	- postgres://, postgresql:// 하드코딩 미발견
- group_db_config 영향:
	- 중앙 DB의 group_db_config에 db_name, db_host, db_port, db_user, db_password 저장/조회 구조 존재
	- tenant alias 런타임 주입에 사용될 수 있음
- 영향 범위:
	- 중앙 로그인 DB
	- cheonan_db 업무 데이터 DB
	- tenant 선택/라우팅
	- tenant_provision / PROVISIONER_DB_* 경로
	- group_db_config 저장값
	- 로컬 개발 서버 .env
	- 운영 서버가 있다면 운영 .env
- 최종 판단:
	- 즉시 교체는 위험
	- 조건부 교체 가능
	- Phase 0에서는 실제 변경하지 않고, 별도 유지보수 단계에서 수행
- 향후 교체 절차:
	1. 중앙 DB/테넌트 DB별 사용 계정 매핑 확인
	2. 운영 포함 .env 반영 대상 확정
	3. group_db_config.db_password 사용 여부 확인
	4. 백업 확인
	5. 유지보수 시간 확보
	6. DB password 변경
	7. .env 및 필요한 group_db_config 값 반영
	8. 앱 재기동
	9. central 로그인과 cheonan_db tenant 기능 점검
	10. 실패 시 이전 password로 롤백
