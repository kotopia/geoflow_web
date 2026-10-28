# GIS 참조코드 적용그룹

상태: 코드·migration·회귀검증 완료. 사용자 진행 지시에 따라 보호된 운영 배포 준비 중.

## 의미와 소유권

중앙 `gis.definition_group`의 UUID/이름 목록을 재사용한다. 기존
`definition_group_scope/layer/field`와 프로젝트 `project_definition.group_id`는
Form 상속과 레이어 선택을 담당한다. 새 참조값 적용 연결은 이 상속 선택과
독립적이다. 지역·프로젝트·테넌트 이름으로 분기하지 않는다. 공통 그룹 행은 없다.

- 중앙 `gis.definition_code_group(code_id,group_id,sort_order)`: 코드와 그룹의 M:N.
  code FK는 코드 삭제 시 관계만 삭제, group FK는 RESTRICT.
- Tenant `gis.project_reference_group(project_id,catalog_l2_id,group_id)`: L2별 M:N.
  project FK는 기존 `prj.projects`를 참조한다. 중앙 L2/group UUID에 대한 DB 간 FK는
  만들 수 없으므로 서버가 현재 프로젝트 scope와 중앙 그룹 존재를 검증한다.
- 기존 코드에 관계를 자동 생성하지 않는다. 관계 0개가 공통이다.

## 해석과 검증

`reference_groups.scope_layers()`는 각 prj.scope_item 행의 L2/L3/L4와 중앙
layer_catalog 연결을 대조해 L2별 적용 레이어를 만든다. 레이어마다 연결된 L2의
선택 그룹만 합산한다. 같은 레이어에 여러 L2가 대응하면 그 L2들에 한해 합집합을
쓴다. 다른 L2 또는 프로젝트 전체 Form 그룹이 참조값을 추가 허용하지 않는다.
범위에서 제거된 L2의 과거 설정은 적용하지 않는다.

코드는 그룹 관계가 없거나 선택 그룹과 교집합이 있으면 포함한다.
공통 `codes_for_field()`와 프로젝트 Final Form이 Reference Catalog에 동일하게
전달된다. 공유 추가 필드는 레이어별 bindings/key로 구분한다. 프로젝트 문맥 없는
참조 조회는 공통 코드만 제공한다. 활성/비활성 표시와 기존 순서는 유지한다.
`reference_constrained`는 필터 결과가 빈 경우에도 코드 도메인이 존재함을 기록한다.
서버 `validate_attributes()`는 허용 코드가 0개여도 임의 문자열을 허용하지 않는다.
NULL은 기존 필수/선택 규칙을 따른다. 이미 저장된 값은 자동 치환/삭제하지 않는다.
그룹 변경 후 허용되지 않는 기존 값의 저장은 기존 서버 검증 오류로 안내한다.

## UI와 권한

중앙 참조코드 행과 생성 폼에 검색 가능한 체크박스 멀티셀렉트를 제공한다.
빈 선택은 공통, 선택값은 이름과 나머지 개수로 표시한다. 기존 중앙 관리자 권한과
CSRF 경계를 그대로 사용한다. 프로젝트 GIS의 기존 폼 설정 화면에서 현재 L2별로
설정하며 기존 project_access_policy.can_edit_project 권한을 재사용한다.
중앙/tenant relation migration이 없는 경우 설정 저장을 거부한다.

코드에 연결된 그룹은 삭제를 차단하고 연결 코드 수를 표시한다. 중앙 삭제 검사도
등록된 tenant의 project_reference_group 사용을 확인한다. 프로젝트 그룹 저장과
중앙 그룹 삭제는 동일 중앙 advisory lock을 사용하며 tenant 저장이 완료될 때까지
유지한다. 참조코드 연결을 명시적으로 모두 해제할 때만 공통으로 바뀐다.

## Revision / 클라이언트

중앙 definition_revision은 code_groups를 포함한다. Final Form revision은 최종
필터 결과와 L2별 그룹/레이어 문맥을 포함한다. Reference Catalog에도 최종 revision을
반환한다. QGIS manifest.form_definition_revision 및 server_snapshot_cache의 기존
fingerprint가 이 revision을 사용한다. QField GeoPackage는 동일 Final Form JSON과
revision을 담는다. 다음 재조회/materialization에서 반영되며 오프라인 파일을 강제로
수정하지 않는다. QGIS/QField에 그룹 판정이나 지역 하드코딩을 추가하지 않는다.

## 배포 준비 / migration / rollback

- 중앙: control.0009_gis_reference_code_groups.
- Tenant: webgisapp.0048_gis_project_reference_groups (각 승인된 tenant migration context).

중앙 GIS foundation이 이미 있는 DB에서는 0009가
관계를 생성한다. GIS를 도입하지 않은 신규 중앙 DB에서는 0009가 no-op이고,
후속 GIS foundation bootstrap의 갱신된 canonical SQL이 관계를 생성한다.
Tenant 0048은 기존 0047과 prj.projects 이후 실행한다. 기존 시설물 물리 schema,
Survey, 사진 정책, 일반 프로젝트 업무 로직에는 DDL/data backfill이 없다.

후속 진행 지시에 따라 기존 보호된 GIS deployment workflow에 전용
`deploy_gis_reference_groups` 명령을 연결한다. `--check`는 실제 테이블 모양·선행
migration·기록을 읽기 전용 확인한다. 서비스 정지 후 `--apply --backup-dir ...`로
control.0009와 webgisapp.0048의 SQL만 실행하고 해당 migration 기록만 추가한다.
다른 미적용 migration을 실행하거나 기록을 위조하지 않는다. control.0008 또는
webgisapp.0047 선행 기록이 없으면 첫 변경 전에 중단한다.

모든 대상의 중앙/tenant baseline·관계 데이터 백업을 먼저 보관하고, 각 DB에서 GIS
테이블 잠금 아래 기존 전체 GIS 행/geometry fingerprint와 관계 데이터를 전후 비교한다.
신규 관계·그룹·코드의 자동 배정은 없다. 새 테이블 외에는 GIS 데이터를 변경하지 않는다.
GIS foundation이 없는 tenant는 건너뛰고 명시적으로 보고한다. DB별 원자적 적용이며
여러 DB 사이의 원자성은 없다. 부분 성공 시 적용된 관계를 유지하고 재실행한다.

서비스 재시작 후 `--verify`를 읽기 전용으로 실행해 실제 프로젝트별 Final Form과
Reference Catalog의 활성 코드 UUID 집합이 동일한지 검증한다. 실제 QGIS/QField
GUI 검증을 대체하지 않는다. 사용자 승인이 필요한 GitHub production 환경을 우회하지
않는다. 기존 운영 definition 재조정 명령은 기존 v3 중앙 상태에서 bootstrap/reseed를
하지 않으며, 기존 표준 fingerprint 검사와 로그인 HTTP 200 확인도 계속 수행한다.

역 migration은 신규 관계 테이블만 제거하고 코드·그룹·프로젝트를 보존한다.
관계 데이터가 있으면 별도 백업이 필요하고 rollback 시 적용 제한이 사라지므로,
반드시 이전 코드로의 통제된 rollback과 함께 수행해야 한다. 운영 rollback도 별도
승인 대상이다. 코드만 먼저 적용돼도 관계가 없으면 기존 값은 공통으로 유지된다.

검증: 공통/단일/다중/미설정/다른 L2/공유 레이어/빈 허용집합/직접 write 거부,
Form-Reference 일치·revision·Snapshot fingerprint, 관리자/프로젝트 권한,
격리 PostgreSQL migration forward/reverse·그룹 삭제 차단·코드 보존을 확인한다.
실제 QGIS/QField UI 및 운영 DB 적용은 별도 배포 전 검증 항목이다.
