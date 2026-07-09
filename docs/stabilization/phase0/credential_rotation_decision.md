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
| AWS key | .env에 실제 값 존재 및 S3 presigned URL 생성에 사용 중 | 교체 권장 | 가능 | 코드 수정 없이 .env 교체 가능, IAM/S3/KMS 권한 확인 필요 |
| DB password | settings.py에 하드코딩되어 있었음 | 권장 | 조건부 가능 | RDS/DB 사용자 비밀번호 변경 후 .env 반영 필요 |
| RRN_SYM_KEY | settings.py에 하드코딩되어 있었고 실제 주민등록번호 암복호화에 사용 중 | 보류 | 즉시 교체 금지 | 기존 rrn_cipher 복호화 불가 위험 |

## 3. RRN_SYM_KEY 특별 주의
- 이 키가 실제 개인정보 암호화에 사용 중인지 확인 필요
- 이미 암호화된 데이터가 있다면 단순 교체 금지
- 교체하려면 기존 데이터 복호화 -> 새 키로 재암호화 절차 필요
- 아직 실제 암호화 데이터가 없다면 새 키로 교체 가능

## 4. 권장 순서
- DJANGO_SECRET_KEY 새 값 생성 및 .env 반영 완료
- AWS key 교체 실행 준비
- DB password 교체 여부 결정
- RRN_SYM_KEY는 Phase 0에서 교체하지 않음

## 5. 아직 하지 않을 것
- AWS key 실제 교체
- DB password 실제 교체
- RRN_SYM_KEY 실제 교체
- AWS key / DB password / RRN_SYM_KEY의 .env 값 변경
- git push
- migrate 실행

## 6. 다음 작업
- AWS key 교체 실행 준비
- DB password 교체 여부 결정
- RRN_SYM_KEY는 Phase 0에서 교체하지 않고 유지
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

- 판단: Phase 0에서 교체 권장
- 이유: .env에 실제 AWS key가 존재했고, 코드 ZIP 또는 AI 검토 과정에 포함됐을 가능성이 있음
- 코드 수정 필요 여부: 없음
- 교체 방식:
	1. AWS IAM에서 새 Access Key 생성
	2. .env의 AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY 교체
	3. 기존 키 비활성화
	4. 업로드/미리보기 기능 테스트
	5. 문제가 없으면 기존 키 삭제
- 주의사항:
	- 기존 S3 버킷은 유지
	- AWS_REGION 유지
	- AWS_S3_BUCKET 유지
	- AWS_KMS_KEY_ID를 쓰고 있다면 새 키 사용자에게 KMS 권한 필요
	- IAM/S3/KMS 권한이 다르면 업로드 또는 다운로드 실패 가능
