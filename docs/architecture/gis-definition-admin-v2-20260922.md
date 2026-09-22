# GeoFlow GIS 중앙 업무정의 관리 확장 — STEP 1/2 현행 분석 및 설계

기준일: 2026-09-22  
기준 소스: `release/stabilized-deploy@f501c05d14f63aa85dc2f6aabc1808cf8a83c0c8`  
범위: GIS 중앙 업무정의 관리만. 계약/프로젝트/인사/파트너/입찰/운영/QGIS 플러그인/QField는 변경하지 않는다.

## STEP 1 — 현행 구조

### 1. 중앙 Authoring Source

중앙 `default` DB의 `gis` schema가 GIS Definition의 단일 authoring source다.

현재 핵심 테이블:

- `gis.definition_group`
- `gis.definition_layer`
- `gis.definition_layer_catalog`
- `gis.definition_field`
- `gis.definition_field_layer`
- `gis.definition_code`
- `gis.definition_group_scope`
- `gis.definition_group_layer`
- `gis.definition_group_field`
- `gis.definition_rule`
- `gis.definition_rule_value`

기존 정의는 `docs/architecture/gis-central-definitions.sql`에 v3로 문서화되어 있다.

### 2. 중앙 관리 화면

- URL: `/control/central/gis/definitions/`
- View: `control/views_gis_admin.py`
- Service: `control/services/gis_definitions.py`
- Template: `control/templates/control/gis/definitions.html`
- 권한: `require_central_admin`
- 동시 수정 보호: PostgreSQL advisory transaction lock 사용

현재 기능:

- 그룹 생성/수정
- 표준 레이어 표시명/순서/활성 수정
- 표준 필드 일반 메타데이터 수정
- 추가 필드 생성/수정
- 코드 정의 및 활성/비활성
- 그룹-레이어/필드 연결
- 조건 규칙
- 기존 일부 삭제

### 3. 기존 Runtime 관계

`geoflow_ops/gis/registry.py`는 코드 하드코딩 대신 중앙 Definition의 활성 레이어를 읽는다.

`geoflow_ops/gis/central_definitions.py`가 중앙 snapshot을 읽어 프로젝트별 폼 정의를 resolve한다.

흐름:

```
central gis.definition_*
        ↓
control.services.gis_definitions.snapshot
        ↓
geoflow_ops.gis.central_definitions
        ↓
Web GIS / Form Definition API / Reference API
        ↓
QGIS/QField consumer
```

tenant DB는 중앙 Definition 복제본을 두지 않는다. tenant의 `gis` schema에는 실제 feature rows와 프로젝트별 선택/구성이 존재한다.

### 4. 현재 구조에서 부족한 관리 기능

이번 요구사항 기준으로 아직 부족한 부분:

- 그룹 자체의 `display_name/sort_order/active/description`
- 그룹 삭제 전 레이어 이동/미분류 처리
- 레이어 신규 생성과 그룹 이동을 한 화면에서 안전하게 관리
- 필드 `active` 상태
- `form_visible` / `table_visible` 분리
- 필드 일괄 편집
- 일반 Definition 수정과 physical schema 변경의 명확한 분리
- Schema change request / preview / approval / tenant apply 상태
- ADD COLUMN / RENAME COLUMN / DROP COLUMN 안전 실행
- 변경 이력
- tenant별 적용 결과
- 영향 분석
- definition/schema version 추적

### 5. 하위 호환 원칙

현재 Runtime 계약을 유지한다.

- 기존 `visible` 필드는 삭제하지 않는다.
- `form_visible`이 없거나 NULL이면 기존 `visible`을 사용한다.
- `table_visible`이 없거나 NULL이면 기존 `visible`을 사용한다.
- 기존 field/layer UUID는 immutable identity로 유지한다.
- `field_name`에 해당하는 physical column rename은 Definition 단독 수정으로 허용하지 않는다.
- QGIS/QField API payload의 기존 키는 제거하지 않는다.
- tenant DB의 `ctr/hr/prj/ops` schema는 Schema Manager 대상에서 코드 수준으로 거부한다.

---

## STEP 2 — 확장 설계

### A. 기존 테이블 최소 확장

#### definition_group

추가 후보:

- `group_code text`
- `display_name text`
- `sort_order integer NOT NULL DEFAULT 0`
- `active boolean NOT NULL DEFAULT true`
- `description text NOT NULL DEFAULT ''`
- `created_at timestamptz`
- `updated_at timestamptz`

기존 `name`은 삭제/변경하지 않고 호환 유지한다.

#### definition_layer

기존 컬럼을 유지하면서:

- `description text NOT NULL DEFAULT ''`
- `updated_at timestamptz`

그룹 소속과 그룹 내 순서는 `definition_group_layer`에서 관리한다.

#### definition_group_layer

추가:

- `sort_order integer NOT NULL DEFAULT 0`

같은 레이어를 필요 시 복수 그룹에 연결할 수 있는 기존 구조를 유지하되, 중앙 관리 UI에서는 대표 그룹 이동을 명시적으로 처리한다.

#### definition_field

추가:

- `active boolean NOT NULL DEFAULT true`
- `form_visible boolean`
- `table_visible boolean`
- `updated_at timestamptz`

기존 `visible`은 하위 호환 fallback으로 유지한다.

### B. 변경 이력

신규 중앙 테이블:

`gis.definition_change_log`

주요 컬럼:

- id
- actor
- target_type: GROUP/LAYER/FIELD/SCHEMA
- target_id
- change_type
- before_value jsonb
- after_value jsonb
- schema_applied boolean
- created_at

Definition mutation은 가능한 범위에서 동일 transaction 내 기록한다.

### C. Schema Migration 요청

신규 중앙 테이블:

`gis.schema_change`

- id
- operation: ADD_COLUMN/RENAME_COLUMN/DEPRECATE/DROP_COLUMN/ALTER_TYPE
- layer_id
- field_id
- old_name
- new_name
- old_type
- new_type
- status: PENDING/APPROVED/APPLYING/APPLIED/PARTIAL_FAILED/FAILED/CANCELLED
- preview_sql
- impact jsonb
- created_by
- approved_by
- created_at / approved_at

신규 중앙 테이블:

`gis.schema_change_tenant`

- change_id
- tenant_group_id
- status
- error_message
- applied_at
- before_schema jsonb
- after_schema jsonb

### D. Schema Manager 안전 경계

허용 schema는 정확히 `gis`만.

허용 identifier:

`^[a-z_][a-z0-9_]*$`

초기 타입 whitelist:

- text
- varchar
- integer
- bigint
- numeric
- double precision
- boolean
- date
- timestamp
- timestamptz
- uuid
- jsonb

범용 SQL 입력창은 만들지 않는다.

SQL은 operation + 검증된 identifier/type을 기반으로 서버 코드가 생성한다.

### E. 적용 흐름

```
Definition 수정/신규
    ↓
Schema 상태 Pending
    ↓
영향 분석
    ↓
SQL Preview
    ↓
중앙 관리자 승인
    ↓
선택 tenant 적용
    ↓
tenant별 성공/실패 기록
```

Definition 저장 성공과 tenant schema 적용 성공은 별도 상태다.

### F. 삭제 정책

Group:
- 레이어가 있으면 물리 삭제 차단
- 다른 그룹 또는 미분류 이동 후 삭제
- 기본은 inactive

Layer:
- 기본은 inactive
- physical table drop과 연결하지 않음

Field:
- 기본은 active=false
- DB column 유지
- DROP COLUMN은 별도 Schema Change로만 실행

### G. 영향 분석 대상

필드/레이어 변경 전 최소 확인:

- group_field
- field_layer
- definition_rule / rule_value
- project_definition JSON 참조
- Form Definition resolve
- tenant physical column 존재 여부
- tenant non-null row count
- layout/action metadata 참조 가능한 범위

### H. 구현 순서

1. 중앙 Definition 테이블 최소 확장
2. 기존 snapshot/resolve 하위 호환
3. Group/Layer/Field 안전 CRUD
4. 필드/레이어 일괄 편집
5. change log
6. Schema Change preview
7. ADD COLUMN
8. RENAME COLUMN
9. tenant별 결과/재시도
10. DROP COLUMN은 마지막

### I. 사용자 승인 반영

현재 tenant GIS DB는 테스트 중인 데이터이므로 GIS schema의 테스트 데이터/테스트 컬럼은 검증 과정에서 변경 또는 삭제할 수 있다.

단 다음은 여전히 금지한다.

- 중앙 운영 데이터의 임의 삭제
- GIS 외 schema 변경
- 서비스 배포/재시작
- QGIS 플러그인/QField 변경
