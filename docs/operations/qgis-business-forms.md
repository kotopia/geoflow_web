# QGIS 업무폼 연결 적용·복구 절차

기준 release: `d34904e8eac35d062c8687e9e9807c6a035abdb2`.
별도 checkout의 브랜치: `fix/qgis-business-form-contract`.
구현 단계에는 운영 DB에 접속하지 않았다. 이후 운영 준비 단계에서 기존 서버 .env로 중앙 DB를 읽기 전용 조회하여 QGIS 설정 사용자의 group `cheonan`, DB alias `cheonan_db`를 확인했다. 정식 tenant secret 조회는 AWS `AccessDeniedException`으로 실패했다. 따라서 tenant DB 사전검사는 미완료이며 운영 DB 변경은 없다. 기존 QGIS의 가장 최근 Snapshot 프로젝트는 `86f52715-3cca-4124-9cc6-cb7c6a7e9c4e`(캐시 코드 26003)이나, tenant에서 실제 존재·귀속을 재확인하지 못했다. 상세 적용 준비 상태는 `business-forms-release-readiness.md`를 따른다.

## 구현 계약

- `current_user`를 기존 프로젝트 목록 JSON에 추가한다. `results/count/scope`는 유지한다.
- 중앙 UUID는 `lookup_user_id_from_request()`를 사용한다. tenant 직원은 기존 `_login_identity()`의 이메일 정규화 규칙을 사용하되 GIS만 0/1/중복을 구분한다. 기존 `current_employee_id()`는 변경하지 않는다.
- `worker_id`는 tenant `hr.employee_profile.id`이다. 신규/변경은 본인 연결 직원만 허용하고 기존 `can_edit_project()` 권한이 있으면 같은 tenant의 삭제되지 않은 다른 직원도 지정할 수 있다. 변경되지 않은 과거 ID와 필드를 생략한 수정은 보존한다. 감사 actor 의미를 변경하지 않는다.
- 기존 project reference catalog에 `current_user`와 `workers:[{id,name,resolved}]`를 추가한다. worker 목록은 현재 연결 직원 및 허용 레이어의 해당 프로젝트 객체가 참조하는 ID만 포함한다. 직원 전체 검색 API를 만들지 않는다.
- catalog의 명시적 빈 허용 집합은 쿼리 없이 빈 결과를 반환한다. `None`의 기존 동작은 보존한다.
- `date/status/worker_id`는 폼을 열 때만 제안하고 폼 저장 때만 저장한다. 코드 label과 code는 분리한다. 직원 이름과 저장 UUID도 분리한다. 업무폼 작업자는 이름을 읽기 전용 표시하며, 대리 지정은 기존 QGIS 필드 편집 경로에서 서버 권한 검증을 거친다.
- 다른 기능의 역할/직원 해석, 도형 대량 생성, project_id 보호, 감사 필드는 변경하지 않는다.

## 적용 전

1. 관리자가 정식 운영 경로에서 group code, DB alias, 프로젝트 UUID를 확인한다. 추정 프로젝트나 임의 DB alias로 진행하지 않는다. 비밀번호/토큰을 문서나 채팅에 기록하지 않는다.
2. `docs/operations/qgis-business-fields-readonly.sql`을 정식 tenant 연결에서 `psql -v project_id=<확인한 UUID> -f ...`로 실행한다. DB·프로젝트·profile·물리 컬럼·metadata·코드 및 worker 집계 결과를 검토한다.
3. 변경 코드와 격리 테스트를 검토한 뒤 별도 승인된 절차로 서버 게시/배포한다. 이번 결과물은 게시되지 않은 로컬 변경이다.
4. 운영 호스트의 기존 Django 환경에서 저장을 중지한 유지보수 구간을 확보한다. metadata는 여러 profile이 참조하므로 대상 시설물과 metadata 편집을 함께 동결한다.
5. 저장되지 않은 QGIS 입력, 편집 버퍼, 미전송 큐를 먼저 보존한다. 구형 필드가 있는 요청을 새 계약에 자동 재전송하지 않는다.

## 사전검사와 적용 명령

저장소 루트에서, 기존 운영 환경을 사용한다. `PYTHONPATH=.`를 설정해 scripts/ops에서 프로젝트 모듈을 읽도록 한다. 예시의 `<...>`는 확인한 식별자로 대체한다.

```sh
PYTHONPATH=. .venv/bin/python scripts/ops/reconcile_gis_business_fields.py \
  --group-code <GROUP> --db-alias <ALIAS> --project-id <PROJECT_UUID>
```

기본 실행은 읽기 전용이다. `GroupDBConfig → 기존 Secrets Manager resolver → tenant 연결` 경로를 사용한다. 대상 데이터나 계정 정보를 수정하지 않는다. 판정 결과만 출력한다. 연결된 profile, 물리 컬럼, field definition, profile 설정과 worker 집계가 포함된다.

확인할 항목:
- 물리 구·신 컬럼 동시 존재 또는 구·신 field definition 동시 존재: 전체 적용 중단. profile 연결과 non-NULL 개수를 보고한다. 자동 삭제/병합하지 않는다.
- 불일치 타입, 다른 code_group_key, 누락된 그룹/참조 필드: 전체 적용 중단.
- GEOFLOW.WORK_STATUS의 유효한 세 label: 미완료/완료/보완필요. 값은 기존 code를 사용한다. 임의 등록/변환하지 않는다.
- 기존 profile enabled/required/editable/visible/sort_order는 보존한다.
- `profile_impact`에 명시적/기본 profile 사용 프로젝트 수와 대상 외 프로젝트 수를 출력한다. 공통 field definition의 다른 profile 연결은 `tables.*.links`에 포함한다. profile 공유 프로젝트에는 누락 연결 추가/오래된 연결 비활성화가 함께 영향을 미친다.
- `column_details`, `constraints`, `triggers` 및 날짜/상태 non-NULL 수·집계 fingerprint를 출력한다. fingerprint는 보조 비교 수단이며 백업을 대체하지 않는다. 충돌이 있어도 inspection을 먼저 출력하고 전체 계획을 중단한다.
- date/worker_id의 기존 DB 기본값·생성 컬럼은 자동 제거하지 않고 충돌로 중단한다. status 기본값이 있으면 등록된 미완료 code의 단순 문자열 literal인지 확인하며, 다른 값/동적 표현식은 중단한다. 기본값이 없으면 폼 저장에서만 미완료 code를 기록하는 기존 정책을 유지한다.
- 실제 컬럼이 삭제된 비공통 필드의 대상 profile 연결만 enabled=false로 비활성화한다. 정의 ID와 다른 profile은 보존한다.
- `ist_ymd/sys_chk`가 이름 변경된 경우 기존 정의 ID로 date/status를 연결한다. 이미 변경된 컬럼은 재변경하지 않는다.
- 없는 공통 필드는 nullable, DB 기본값 없이 추가한다. 현재 프로젝트의 실제 profile에 누락된 연결만 추가한다. 기존 날짜/상태 데이터는 갱신하지 않는다.

별도 운영 적용 승인이 있을 때만:

```sh
PYTHONPATH=. .venv/bin/python scripts/ops/reconcile_gis_business_fields.py \
  --group-code <GROUP> --db-alias <ALIAS> --project-id <PROJECT_UUID> \
  --apply --backup-dir <NEW_PRIVATE_BACKUP_DIRECTORY>
```

`pg_dump`가 PATH에 있어야 한다. 백업은 대상 다섯 시설물과 `gis.meta_field_def/profile_field`를 포함하는 custom archive이며, `metadata-before.json`도 생성한다. 기존 백업 파일은 덮어쓰지 않는다. 접속 정보는 subprocess 환경으로만 전달한다. 백업 실패 시 적용하지 않는다.

적용은 한 transaction에서 advisory lock과 table lock을 취득하고 다시 사전검사한다. 모든 충돌이 없는 경우에만 물리 변경/필요한 행 갱신을 실행한다. 적용 후 같은 planner의 변경 건수가 0인지 검증하고 commit한다. 전체 seed는 실행하지 않는다.

## 적용 후 검증

1. 동일 명령을 --apply 없이 실행해 operations=0을 확인한다.
2. 읽기 전용 SQL에서 기존 날짜·상태 집계와 profile 제한이 보존됐는지 확인한다. 의심 worker 값은 보고만 한다.
3. 인증된 QGIS 목록의 current_user, manifest의 다섯 레이어 date/status/worker_id 및 code_group_key, 기존 catalog의 승인 그룹과 제한된 workers 목록을 확인한다.
4. linked/unlinked/ambiguous, 현재/과거/미해결 작업자, 프로젝트 관리자 대리 지정 및 타 tenant 지정 거부를 확인한다.
5. 보존된 입력의 안전한 전환 후 신규 Snapshot을 별도 로컬 경로에서 확인한다. 운영 대상의 실제 저장 테스트는 별도 승인 범위 내에서 시행한다.

## 복구

- commit 전 실패: transaction rollback. 기존 DB 상태 유지.
- commit 후, 백업 이후 쓰기가 전혀 없고 유지보수 동결이 유지되는 경우: 먼저 백업을 별도 복구 DB에서 검증한다. 승인 후 정식 tenant 연결 환경에서 `pg_restore --clean --if-exists --single-transaction --dbname=<확인한 DB> <backup>/gis-before-business-fields.dump`를 사용한다. 백업 범위는 위 7개 테이블이며 schema 전체를 drop하지 않는다. 외부 FK 때문에 거부되면 강제 cascade하지 말고 복구 DB에서 선택 복구한다.
- 백업 이후 쓰기가 있으면 위 명령을 운영 DB에 실행하지 않는다. 백업을 별도 DB에 복원하여 이후 데이터와 metadata 차이를 검토하고 선택 복구한다. 새 날짜/작업자 값을 제거하거나 일괄 치환하지 않는다.
- 서버 코드만 되돌리는 경우 먼저 운영 적용 담당자가 이전 배포 SHA와 schema 호환성을 확인한다. 자동 배포/재시작/역 migration은 제공 도구에서 수행하지 않는다.
- 물리 FK는 이번 변경에 포함하지 않는다. 미해결 ID 집계를 확인한 후 별도 변경으로 검토한다.

## 구형 로컬 작업 보존·전환

1. QGIS 폼 미저장 입력, 레이어 편집 버퍼, SQLite pending/outbox는 서로 다른 상태다. 먼저 폼 입력을 보존하고 QGIS 편집을 해결한다. 서버 저장이 승인되지 않은 경우 전송하지 않는다.
2. 프로그램이 파일을 쓰지 않는 상태에서 프로젝트 디렉터리 전체와 .qgz, manifest, .gpkg 및 존재하는 -wal/-shm 파일을 별도 보존한다. 실행 중인 SQLite 파일을 단일 파일 복사로 백업하지 않는다. 필요 시 SQLite backup API를 사용한다.
3. '연결 진단'의 manifest_missing/snapshot_missing/pending_legacy_fields 및 pending/outbox 개수를 구분한다. 진단은 mode=ro이며 큐나 Snapshot을 변경하지 않는다.
4. 미전송 요청에 ist_ymd/sys_chk가 있으면 자동 이름 변환이나 큐 삭제를 하지 않는다. 기존 계약으로 안전하게 완료할 수 있는지 먼저 판단하거나, 보존본에서 검토한 변경만 새 계약에서 재입력한다. 기존 outbox의 idempotency ID를 다른 내용으로 재사용하지 않는다.
5. 보존·정합성 확인 후 사용자가 명시적으로 새 프로젝트 사본을 열어 새 manifest/Snapshot을 받는다. 기존 프로젝트를 강제 재다운로드하거나 삭제하지 않는다.

## 검증 재현

운영 준비 단계의 추가 변경에 한해서 신규 검사 3개(공유 profile·기본값·제약·데이터 보존 PostGIS 1개, 기본값 충돌 순수 테스트 2개), 변경 Python 4개 문법, 전체 읽기 전용 SQL의 격리 psql 실행이 통과했다. 아래 기존 전체 테스트는 이유 없이 재실행하지 않았다.

2026-09-14 로컬 검증 결과: 플러그인 순수 테스트 13개, 서버 DB-free 136개, 격리 PostgreSQL 16/PostGIS 14개, QGIS 4.2.2/Qt offscreen 4개 모두 통과했다. QGIS 테스트는 5개 폼 각각의 NULL 제안/기존 값 보존/중복 연결 시나리오와 패널 표시를 검사한다. 실제 commit 후 큐 적재·자동 동기화 예약·편집 중 전송 지연 경로를 호출하며 네트워크 전송은 대역으로 확인한다. PostGIS에서는 실제 Changeset 저장·재전송 멱등성·revision/delta·GeoPackage 생성을 확인했다.

대상 7개 테이블의 pg_dump custom archive 생성 및 별도 `geoflow_business_restore_test` DB에서 `pg_restore --clean --if-exists --single-transaction` 복구도 성공했다. 운영의 추가 FK/의존성까지 검증한 것은 아니다. 전체 seed는 새 격리 테스트 DB의 fixture 구성에만 사용했다.

사용자의 실행 중인 QGIS 세션, 운영 DB 사전검사, 운영 HTTP/WebSocket 자동 동기화와 실제 운영 저장은 미검증이다. 현재 설치 폴더의 플러그인 변경과 별도 서버 checkout의 변경은 각각 검토·전달해야 하며, 서버 저장소의 기존 integrations 플러그인 사본을 이번 작업에서 일괄 덮어쓰지 않았다.

- 순수 플러그인: `python -B -m unittest discover -s tests -p test_user_context.py -v`
- 로컬 보존 진단: `python -B -m unittest discover -s tests -p test_contract_diagnostics.py -v`
- 실제 QGIS/Qt offscreen: QGIS python으로 `tests/test_business_forms_qgis.py`. 운영 QGIS 세션 대신 격리 memory layer/설정 디렉터리를 사용한다.
- 서버 DB-free: `python scripts/ci/run_gis_unit_tests.py` (실제 GDAL/GEOS 사용).
- PostGIS: 별도 localhost 55000..55999 포트, geoflow_test 역할, 테스트 전용 클러스터에서만 `GEOFLOW_RUN_ISOLATED_POSTGIS=1 GEOFLOW_TEST_PGPORT=<PORT> python scripts/ci/test_business_fields_postgis.py`. 이 스크립트는 이름이 고정된 *_test DB만 생성/초기화한다. 운영 연결 변수는 읽지 않는다. Windows에서는 PostgreSQL GDAL/GEOS DLL 경로와 DLL directory 등록이 필요하다.

## 사용자 QGIS 확인

플러그인을 다시 로드한 뒤 프로젝트를 열고 레이어 패널의 코드 새로고침/연결 진단을 확인한다. 다섯 업무폼에서 기존 이름·날짜 보존, 빈 값 제안, 저장 전 미변경, 저장 후 상태 label에 대응한 code 및 직원 UUID 전송을 확인한다. 패널을 모두 접으면 아이콘만 남아야 한다. 운영 저장 테스트는 운영 적용 승인 후 수행한다.
