# GeoFlow GIS 데이터 모델 설계 원칙 v0.2

- 상태: 구현 기준 아키텍처
- 기준일: 2026-09-03
- 적용 범위: GeoFlow WebGIS, QGIS, QField, PostGIS tenant DB
- 상세 구현 전제: 운영 DB 적용은 별도 승인 없이 수행하지 않는다.

## 1. 목적
GeoFlow의 WebGIS, QGIS, QField가 하나의 GIS 데이터 모델을 사용하도록 하고, 기존 GeoFlow의 계약·프로젝트·직원·권한·이벤트 체계와 자연스럽게 연결한다.

GeoFlow Server/PostGIS를 데이터와 권한의 Source of Truth로 유지하며, QGIS/QField는 별도의 독립 DB 체계를 만들지 않는다.

## 2. 스키마 원칙
- 신규 GIS DB schema는 tenant DB 내부의 `gis` 하나만 사용한다.
- 기존 `ctr`, `hr`, `prj`, `ops` schema는 GIS 도입 때문에 재설계하지 않는다.
- 상수, 하수, 도로, 전기, 통신, 가스, 열배관 등 공간정보 도메인은 우선 `gis` schema 안에 수용한다.
- 200~300개 시설물 테이블까지 증가할 수 있음을 전제로 한다.
- 테이블 수 자체를 이유로 도메인별 schema를 선분리하지 않는다. 실제 운영상 경계가 명확해질 때만 재평가한다.

## 3. 기존 표준명 보존과 PostgreSQL 물리명
공공 GIS 및 기존 작업에서 사용하던 테이블·필드의 의미와 명칭을 최대한 보존한다.

예:
- 논리/표준명: `WTL_PIPE_LM`, `WTL_VALV_PS`, `SWL_PIPE_LM`
- PostgreSQL 물리명: `gis.wtl_pipe_lm`, `gis.wtl_valv_ps`, `gis.swl_pipe_lm`

PostgreSQL physical identifier는 lowercase unquoted를 기본으로 한다. Quoted uppercase identifier는 사용하지 않는다.

동일 원칙을 필드에도 적용한다.
- 표준명: `FTR_CDE`, `FTR_IDN`, `VAL_STD`
- 물리명: `ftr_cde`, `ftr_idn`, `val_std`

표준 대문자명은 metadata와 UI/Export에서 보존한다.

## 4. 기존 필드와 GeoFlow 확장 필드
- 기존 표준 필드명은 가능한 한 유지한다.
- 잘못된 데이터 타입까지 그대로 복제하지는 않는다. PostgreSQL/PostGIS에 적절한 타입을 사용한다.
- 문자열 규격처럼 구조화가 부족한 값은 원본 필드를 남기고 구조화 필드를 추가한다.

예:
- `val_std`: 원본/표준 규격 표현
- `val_std_h`: 가로
- `val_std_v`: 세로
- `val_std_d`: 깊이/높이 등 세 번째 차원

`_H`, `_V`, `_D`의 정확한 의미는 feature metadata에서 한글명·단위와 함께 정의한다.

## 5. 기존 GeoFlow 업무 스키마 참조
GIS에서 다음 정보를 별도로 복제하지 않는다.
- 계약: `ctr`
- 프로젝트: `prj`
- 직원/작업자: `hr`
- 운영설정/이벤트: `ops`

기존의 `PJ_CODE`, `WORKER` 같은 문자열/숫자 중복 저장은 신규 구조의 기준으로 삼지 않는다.

신규 GIS 데이터에서는 가능한 경우 다음과 같이 연결한다.
- `project_id` → 기존 GeoFlow 프로젝트
- `worker_id`, `created_by`, `updated_by` → 기존 GeoFlow 직원/사용자 식별자

기존 데이터 Import 시 `pj_code`, `worker` 원문은 필요하면 원본 lineage에 보존할 수 있다.

## 6. Tenant와 Project scope
GeoFlow는 중앙 Control DB + tenant별 독립 tenant DB 구조다. 따라서 tenant DB의 GIS 테이블에 `tenant_id`를 반복 저장하는 것을 기본 규칙으로 하지 않는다.

대신 feature별 scope를 metadata로 명확히 구분한다.
- `PROJECT`: 특정 프로젝트에서 생성·관리되는 데이터
- `TENANT`: tenant 공통 자산/기존 GIS 데이터
- `REFERENCE`: 기준/참조 데이터

프로젝트 귀속 데이터에는 `project_id`를 사용한다.

QGIS가 향후 PostGIS에 직접 접근하는 경우에는 project-scoped View/RLS/short-lived role/proxy 중 검토된 방식을 사용해야 한다. 현재 단계에서 특정 방식을 데이터 모델에 강제하지 않는다.

## 7. 식별자와 감사 필드
- GeoFlow 내부 PK는 UUID `id`를 기본으로 한다.
- 기존 `GID`, `FTR_IDN` 등 외부/관리 식별자는 별도 필드로 유지한다.
- 날짜는 `date`, 시간은 `timestamptz`를 기본으로 한다.
- 필요 시 `created_at`, `updated_at`, `created_by`, `updated_by`를 추가한다.
- 외부 납품 형식이 문자열 날짜를 요구하면 Export 시 변환한다.

## 8. Metadata / Reference / Profile
`gis` schema 내부의 관리용 테이블은 역할 prefix로 구분한다.

### Metadata
- `meta_feature_type`: 시설물/레이어 정의
- `meta_field_def`: 필드 정의, 단위, 타입, 위젯, 필수 여부, 표준명

### Reference
- `ref_code_group`
- `ref_code_value`

GIS 전문 코드는 `ops.settings_nodes`에 혼합하지 않고 GIS reference 영역에서 관리한다. 기존 업무 공통 설정은 계속 `ops.settings_nodes`가 담당한다.

### Profile
- `profile`
- `profile_feature`
- `profile_field`

Profile은 지자체 또는 사업별로 어떤 시설물/필드를 사용하는지 정의한다.

Metadata/Profile은 WebGIS에서 직접 Form 생성에 사용할 수 있다. QGIS/QField에서는 metadata를 실시간 DB UI 엔진처럼 해석하는 것을 전제로 하지 않는다.

## 9. QGIS/QField Materialization 원칙
QGIS/QField 구성 흐름은 다음과 같다.

`GeoFlow metadata/profile → 프로젝트별 QGIS/QField 구성 생성 → .qgs/.qgz/QField package → QGIS/QField`

즉 metadata/profile은 Source of Truth이며, QGIS 프로젝트의 레이어·Form·Value Relation·Style 설정은 필요 시 materialize한다.

QGIS Plugin은 유지한다.
- GeoFlow 로그인
- 접근 가능한 프로젝트 선택
- 프로젝트/QGIS package 연동
- 동기화 및 전문 편집 UX
- 서버 통신

권한·업무규칙·민감정보는 Plugin에 두지 않는다.

## 10. 사업/지자체별 확장 필드
전면 EAV도, 전면 JSONB도 사용하지 않는다.

### Physical column 대상
- 공공 표준 핵심값
- 여러 사업에서 반복되는 값
- QGIS/QField에서 직접 입력하는 값
- 심볼/라벨/필터/통계에서 자주 쓰는 값
- 납품 핵심값

### Metadata/Profile 대상
- 필드 사용 여부
- 필수/선택
- Form 그룹/순서
- 코드 그룹
- 프로젝트별 활성화

### 제한적 확장 저장
- 임시/희소/원본보존 값은 `ext_data JSONB` 등으로 저장할 수 있다.
- 관계형 확장 값 저장 방식은 QField 오프라인 PoC 후 사용 범위를 확정한다.
- 여러 프로젝트에서 반복되는 확장필드는 physical column 승격을 검토한다.

## 11. 공통 측량 `gis.survey`
상수·하수·도로·전기·통신·가스·열배관별로 별도 survey 테이블을 만들지 않는다.

기존 `survey`와 `h_survey`는 공통 `gis.survey` 개념으로 통합한다.

기본 개념 필드:
- `id` UUID
- `project_id`
- `worker_id`
- `name`
- `code`, `survey_code`
- `survey_date`, `surveyed_at`
- `x`, `y`, `z`
- `geom`
- GNSS solution/quality/PDOP/antenna height 등
- 비고 및 원시 메타데이터

## 12. Survey raw/final lineage
측량 원시값과 보정/편집 후 값을 구분할 수 있어야 한다.

예:
- `raw_x`, `raw_y`, `raw_z`, `raw_geom`
- `x`, `y`, `z`, `geom`
- `raw_data JSONB`

원시값을 덮어쓰지 않고 최종값과 함께 보존하는 것을 기본 원칙으로 한다.

## 13. `gis.survey_link`
측량 대상 시설물은 공간검색으로 후보를 찾을 수 있지만 공간검색 결과 자체를 관계로 간주하지 않는다.

공간검색/코드/프로젝트 문맥으로 찾은 최종 매칭 결과는 `gis.survey_link`에 명시적으로 저장한다.

권장 필드:
- `id`
- `survey_id`
- `feature_type_id` → `meta_feature_type`
- `target_id` → 대상 시설물 UUID의 논리 참조
- `match_method`
- `match_distance`
- `match_confidence`
- `confirmed_by`
- `confirmed_at`

수백 개 시설물 테이블 각각에 survey FK를 추가하지 않는다.

## 14. 공통 도로 기준 데이터 `gis.doro`
`gis.doro` 명칭을 유지한다.

`doro`는 정식 도로대장 납품 테이블이 아니라 지하시설물 관로를 측량할 때 도로상 위치를 판단하기 위한 공통 기준 공간데이터다.

기본 역할:
- 도로 경계/기준선 등 현장 기준 객체
- 관로의 도로상 상대 위치 판단
- 상수/하수/전기/통신/가스/열배관 공통 사용

향후 정식 도로대장(`RDL_*` 등)과는 별도 역할로 관리한다.

필요 시 다음을 둔다.
- `project_id`
- `source_type`
- `road_link_id` nullable: 향후 정식 도로 객체와 연결 가능

## 15. QC / Error
신규 표준 모델에는 `wtl_error`, `swl_error` 같은 오류 공간시설물 테이블을 만들지 않는다.

오류는 공간검색·거리·위상·속성 검증으로 계산한다.

다만 후속 QC workflow에서는 검수 이력을 위한 비시설물 audit table을 둘 수 있다.
- `qc_run`
- `qc_issue`

이는 오류 시설물 Layer가 아니라 검수 실행/발견/수정 이력을 보존하기 위한 테이블이다.

## 16. Import lineage
초기에는 `import_batch` 수준의 이력을 권장한다.
- 프로젝트
- 원본 파일/원본 시스템
- Profile
- 작업자
- Import 일시
- 성공/실패/경고 건수
- 원본 파일 S3 위치 등

모든 성공 row의 원본/변환 값을 중복 저장하는 대규모 `import_log`는 초기 필수사항으로 두지 않는다. 오류/경고 row 중심 상세기록은 후속 구현에서 검토한다.

## 17. 초기 Feature Registry
초기 physical feature 종류는 사용자가 제공한 `DB테이블--.xlsx`의 상수/하수 테이블 종류를 기준으로 한다.

### 공통
- `gis.doro`
- `gis.survey` (`survey`, `h_survey` 통합)
- `gis.survey_link`

### 상수
- `gis.wtl_etc_ps`
- `gis.wtl_fire_ps`
- `gis.wtl_flow_ps`
- `gis.wtl_manh_ps`
- `gis.wtl_pipe_lm`
- `gis.wtl_pipe_ps`
- `gis.wtl_plan_lm`
- `gis.wtl_sply_ls`
- `gis.wtl_valv_ps`

### 하수
- `gis.swl_conn_ls`
- `gis.swl_etc_ps`
- `gis.swl_manh_ps`
- `gis.swl_pipe_as`
- `gis.swl_pipe_lm`
- `gis.swl_pipe_ps`
- `gis.swl_side_ls`
- `gis.swl_spot_ps`

### 제외/통합
- `polygon`: 원본 비고에 따라 별도 표준시설물로 만들지 않고 `wtl_plan_lm` 사용
- `wtl_error`: 제외
- `swl_error`: 제외
- `survey`, `h_survey`: `gis.survey`로 통합

## 18. Geometry/SRID 원칙
기존 GeoFlow WebGIS의 저장 기준과 호환성을 유지하되, 각 신규 physical table의 geometry subtype(Point/LineString/Polygon)과 SRID는 실제 기존 DB/납품 Profile과 PoC로 검증 후 migration에 고정한다.

현재 registry에서 `_PS`는 Point, `_LM`/`_LS`는 Line 계열로 분류할 수 있으나, workbook 자체가 정확한 geometry subtype/SRID를 명시하지 않는 경우 최종 DDL에서 근거 없이 확정하지 않는다.

## 19. WebGIS / QGIS / QField 역할
### WebGIS
- 조회
- 프로젝트/레이어 현황
- 일반 편집
- 정위치 편집
- QC 표시

### QGIS
- 전문 편집
- 정위치/구조화 편집
- 대용량 공간 작업
- 성과품 제작 연계

### QField
- GNSS 현장측량
- 속성 입력
- 사진/현장조사
- 오프라인 작업 및 동기화

세 클라이언트는 동일한 GeoFlow GIS 데이터 모델과 project/profile 문맥을 사용한다.

## 20. 구현 순서
1. 아키텍처 문서 + Feature Registry + 기본 GIS 화면
2. `gis` foundation metadata/ref/profile/survey/doro 설계
3. 실제 tenant DB를 복제한 disposable PostGIS에서 migration rehearsal
4. 상수 9개 physical table
5. 하수 8개 physical table
6. WebGIS 연결
7. QGIS 프로젝트 생성/Plugin 연결
8. QField package/offline PoC
9. 도로대장
10. 전기/통신/가스/열배관 순차 확장

## 21. 변경 통제
GIS schema 또는 데이터 모델을 변경할 때는 이 문서를 기준으로 한다.

특히 아래 변경은 문서 갱신 없이 임의로 수행하지 않는다.
- 신규 schema 분리
- 표준 테이블명 재명명
- survey 도메인별 분리
- tenant_id 반복 저장
- 전면 EAV 전환
- QGIS/QField 독립 DB 도입
- 운영 tenant DB migration 적용

## 최종 설계 문장
**GeoFlow GIS는 tenant DB의 단일 `gis` schema 안에서 기존 공공 GIS 테이블/필드 의미를 최대한 유지하고, 부족한 구조만 확장한다. 프로젝트·직원·계약·권한은 기존 GeoFlow를 참조하며, 사업별 차이는 Metadata/Profile과 제한적 확장 저장으로 흡수한다. 공통 survey는 단일 모델로 유지하되 `survey_link`로 시설물 lineage를 명시적으로 보존하고, GeoFlow metadata/profile을 WebGIS 및 생성된 QGIS/QField 구성의 Source of Truth로 사용한다.**