# settings.py 환경변수화 리팩터링 계획 (Phase 0)

## 0. settings.py 실제 경로 확인
- 프로젝트 루트: C:\GeoFlow\geoflow_web
- 확인 결과: settings.py는 C:\GeoFlow\geoflow_web\geoflow_project\settings.py 한 곳만 존재
- C:\GeoFlow\geoflow_web\settings.py 파일은 없음
- 본 문서의 settings.py 경로 표기는 모두 geoflow_project/settings.py 기준으로 통일

## 1. 현재 settings.py에서 보안상 수정이 필요한 항목
- SECRET_KEY
- DEBUG
- ALLOWED_HOSTS
- DATABASES default
- cheonan_db 관련 TENANT_DB 설정
- AWS 관련 설정
- RRN_SYM_KEY
- CSRF_COOKIE_SECURE
- SESSION_COOKIE_SECURE
- CSRF_TRUSTED_ORIGINS

## 2. 각 항목의 현재 상태

| 항목 | 파일 경로 | 줄 번호 | 현재 상태 | 하드코딩/환경변수 |
|---|---|---:|---|---|
| SECRET_KEY | geoflow_project/settings.py | 38 | 코드 내 문자열 직접 할당 | 하드코딩 |
| DEBUG | geoflow_project/settings.py | 41 | True 고정 | 하드코딩 |
| ALLOWED_HOSTS | geoflow_project/settings.py | 43 | 리스트 상수 직접 선언 | 하드코딩 |
| CSRF_TRUSTED_ORIGINS | geoflow_project/settings.py | 44 | 리스트 상수 직접 선언 | 하드코딩 |
| CSRF_COOKIE_SECURE | geoflow_project/settings.py | 53 | False 고정 | 하드코딩 |
| SESSION_COOKIE_SECURE | geoflow_project/settings.py | 54 | False 고정 | 하드코딩 |
| DATABASES(default) NAME/USER/HOST/PORT | geoflow_project/settings.py | 282, 285-289 | default DB 접속정보가 settings에 직접 선언 | 하드코딩 |
| DATABASES(default) PASSWORD | geoflow_project/settings.py | 287 | default DB 비밀번호가 settings에 직접 선언 | 하드코딩 |
| TENANT_DB_USER/PASSWORD/HOST/PORT | geoflow_project/settings.py | 219-222 | os.getenv 체인으로 로드 | 환경변수 기반 |
| DATABASES(cheonan_db) USER/PASSWORD/HOST/PORT | geoflow_project/settings.py | 301-304 | TENANT_DB_* 변수 참조 | 환경변수 기반 |
| DATABASES(cheonan_db) NAME | geoflow_project/settings.py | 300 | cheonan_db 고정 문자열 | 하드코딩 |
| RRN_SYM_KEY | geoflow_project/settings.py | 386 | 코드 내 문자열 직접 할당 | 하드코딩 |
| AWS 관련 설정 (settings.py 내부) | geoflow_project/settings.py | 16, 27 | dotenv 로딩만 수행, AWS 키 변수는 직접 정의하지 않음 | 간접(환경 로드만) |
| AWS 실제 사용 위치(참고) | geoflow_ops/services/s3_service.py | 33-35, 42, 59 | AWS_* 값을 os.environ에서 읽음 | 환경변수 기반 |

보안 주의:
- 실제 SECRET_KEY 값, DB 비밀번호 값, AWS 키 값은 본 문서에 기록하지 않음.

## 3. 변경 계획

### 3.1 os.getenv로 변경할 항목
- SECRET_KEY
  - 변경 방향: os.getenv("DJANGO_SECRET_KEY")로 로드
  - 정책: 값이 없으면 즉시 예외 발생(RuntimeError)
- DEBUG
  - 변경 방향: os.getenv("DJANGO_DEBUG", "False") 기반 bool 파싱
- ALLOWED_HOSTS
  - 변경 방향: os.getenv("DJANGO_ALLOWED_HOSTS", "")를 쉼표 분리하여 리스트화
- CSRF_TRUSTED_ORIGINS
  - 변경 방향: os.getenv("DJANGO_CSRF_TRUSTED_ORIGINS", "")를 쉼표 분리
- CSRF_COOKIE_SECURE
  - 변경 방향: os.getenv("DJANGO_CSRF_COOKIE_SECURE", "True") 기반 bool 파싱
- SESSION_COOKIE_SECURE
  - 변경 방향: os.getenv("DJANGO_SESSION_COOKIE_SECURE", "True") 기반 bool 파싱
- DATABASES default
  - 변경 방향: CENTRAL_DB_NAME, CENTRAL_DB_USER, CENTRAL_DB_PASSWORD, CENTRAL_DB_HOST, CENTRAL_DB_PORT를 os.getenv로 통일
  - 참고: 현재 TENANT_DB_*는 이미 os.getenv 기반이므로 유지/정리 중심으로 진행
- cheonan_db NAME
  - 변경 방향: os.getenv("TENANT_DB_NAME", "cheonan_db") 사용 검토
  - 원칙: cheonan_db는 현재 실제 업무 데이터가 있는 tenant DB이므로, 운영에서는 .env에 TENANT_DB_NAME=cheonan_db를 명시 권장
- RRN_SYM_KEY
  - 변경 방향: os.getenv("RRN_SYM_KEY")로 로드
  - 정책: 값이 없으면 예외 처리 또는 기능 비활성/명시적 실패
- AWS 관련
  - settings.py에는 AWS 직접 정의가 없으므로, 환경변수 계약(.env/.env.example) 정합성 강화
  - 실제 코드(geoflow_ops/services/s3_service.py) 사용 변수만 반영: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, AWS_S3_BUCKET, AWS_KMS_KEY_ID

### 3.2 사용할 환경변수 이름(제안)
- DJANGO_SECRET_KEY
- DJANGO_DEBUG
- DJANGO_ALLOWED_HOSTS
- DJANGO_CSRF_TRUSTED_ORIGINS
- DJANGO_CSRF_COOKIE_SECURE
- DJANGO_SESSION_COOKIE_SECURE
- CENTRAL_DB_NAME
- CENTRAL_DB_USER
- CENTRAL_DB_PASSWORD
- CENTRAL_DB_HOST
- CENTRAL_DB_PORT
- TENANT_DB_NAME
- TENANT_DB_USER
- TENANT_DB_PASSWORD
- TENANT_DB_HOST
- TENANT_DB_PORT
- PROVISIONER_DB_HOST
- PROVISIONER_DB_PORT
- PROVISIONER_DB_USER
- PROVISIONER_DB_PASSWORD
- ENABLE_TENANT_PROVISIONING
- RRN_SYM_KEY
- AWS_ACCESS_KEY_ID
- AWS_SECRET_ACCESS_KEY
- AWS_REGION
- AWS_S3_BUCKET
- AWS_KMS_KEY_ID

### 3.3 .env에 있어야 하는 항목
- 운영/공통 필수
  - DJANGO_SECRET_KEY
  - DJANGO_DEBUG
  - DJANGO_ALLOWED_HOSTS
  - DJANGO_CSRF_TRUSTED_ORIGINS
  - DJANGO_CSRF_COOKIE_SECURE
  - DJANGO_SESSION_COOKIE_SECURE
  - CENTRAL_DB_NAME, CENTRAL_DB_USER, CENTRAL_DB_PASSWORD, CENTRAL_DB_HOST, CENTRAL_DB_PORT
  - RRN_SYM_KEY
- 테넌트/프로비저닝
  - TENANT_DB_NAME, TENANT_DB_USER, TENANT_DB_PASSWORD, TENANT_DB_HOST, TENANT_DB_PORT
  - PROVISIONER_DB_HOST, PROVISIONER_DB_PORT, PROVISIONER_DB_USER, PROVISIONER_DB_PASSWORD
  - ENABLE_TENANT_PROVISIONING
- 파일 업로드/AWS
  - AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, AWS_REGION, AWS_S3_BUCKET
  - AWS_KMS_KEY_ID(선택)

### 3.4 .env.example placeholder 항목
- 현재 존재 확인: .env.example 2-3, 6-10, 13-16, 20-21, 26-29
- 추가/정비 권장 placeholder
  - DJANGO_SECRET_KEY=change-me
  - DJANGO_DEBUG=False
  - DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
  - DJANGO_CSRF_TRUSTED_ORIGINS=http://localhost:8000,http://127.0.0.1:8000
  - DJANGO_CSRF_COOKIE_SECURE=True
  - DJANGO_SESSION_COOKIE_SECURE=True
  - TENANT_DB_NAME=cheonan_db
  - RRN_SYM_KEY=change-me-strong-key

## 4. 배포용 기본값 원칙
- DEBUG 기본값은 False
- 운영에서는 CSRF_COOKIE_SECURE=True
- 운영에서는 SESSION_COOKIE_SECURE=True
- 로컬 개발에서 http://localhost 사용 시 DJANGO_CSRF_COOKIE_SECURE=False, DJANGO_SESSION_COOKIE_SECURE=False 허용 가능
- 기본 원칙은 운영 보안 우선이며, 운영 환경 기본값은 secure=True로 유지
- ALLOWED_HOSTS는 환경변수 기반
- SECRET_KEY가 없으면 오류를 내도록 처리

## 5. 수정하지 않을 항목
- geoflow_ops.apps.label
- migrations
- DATABASE schema
- cheonan_db 데이터
- tenant_provision.py
- migrate_all_tenants.py

## 6. 실제 수정 전 확인해야 할 사항
- python-dotenv 사용 여부: 사용 중
  - 근거: geoflow_project/settings.py 16, 27
- requirements.txt에 python-dotenv 존재 여부: 존재
  - 근거: requirements.txt 6
- .env.example 존재 여부: 존재
  - 근거: .env.example (프로젝트 루트)
- 현재 서버/로컬 실행 방식
  - 로컬 개발은 가상환경(venv) 활성화 후 Django manage.py 명령 사용 패턴
  - 문서 근거: docs/cheonan_db_account_migration.md 109 (python manage.py runserver)
  - 터미널 근거: venv\Scripts\Activate.ps1 활성화 이력 확인

---

본 문서는 읽기 전용 점검 결과를 바탕으로 작성한 계획서이며, settings.py/.env/.env.example/DB에는 변경을 가하지 않았다.
