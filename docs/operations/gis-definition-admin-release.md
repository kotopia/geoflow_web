# GIS 업무정의 관리 — 구현 후보와 적용 범위

기준 release: d8b0ee7acf2ed2956b388c8a3afccd2f20c4685e.
2026-09-16 제공받은 중앙/cheonan 구조 보고서의 해시와 완료 기록을 대조했다.
보고서 원문과 운영 행/연결정보는 저장소에 포함하지 않는다.

## 구현

- 중앙 `GIS 업무정의`: 중앙 관리자만 접근하며 명시적으로 선택한 tenant의 기존 정식 resolver로 연결한다. 세션의 tenant alias를 바꾸지 않는다.
- 업무 그룹은 기존 gis.profile을 사용한다. 새로운 업무 그룹 생성 시 선택한 기존 프로필의 시설물/물리 필드 제한을 복사한다. 프로젝트마다 프로필을 복제하지 않는다.
- 기존 reference group/value를 직접 관리하며 저장 code와 label을 분리한다. 사용 중인 값은 비활성화하고 물리 삭제하지 않는다. 기존 유효기간은 보존한다.
- 추가 항목은 희소 속성/사진/기존 survey_link 관계만 지원한다. 기존 물리 필드를 추가 항목 정의로 복제하지 않는다.
- 프로젝트 GIS 상세 `폼 및 첨부 구성`: 기존 프로젝트 권한과 Layer Plan을 확인한다. 그룹 선택, 공개 항목 추가, 프로젝트 전용 항목 생성·제외를 지원한다.
- 그룹에서 상속한 항목은 프로젝트 화면에서 제거할 수 없다. 완료 시 입력 필요 여부와 필수 표시는 분리한다.
- 공통 승격 시 item ID를 유지한다. 프로젝트 링크도 유지하며 resolver에서 하나의 항목으로 합친다. 다른 프로젝트의 private 항목은 조회·추가할 수 없다.
- `/gis/projects/<uuid>/api/form-definition/`: 기존 QGIS 인증/프로젝트 권한으로 최종 정의와 해당 항목에서 사용한 활성 참조코드만 반환한다.

## 아직 포함하지 않는 기능

이 후보는 **정의 관리 기능**이다. scalar 값을 시설물 ext_data에 저장하는 새 입력 UI,
사진 업로드·삭제, QField 오프라인 관계 패키지, 완료 시 신규 항목 강제 검증은 구현하지 않았다.
API는 `client_integration_required=true`를 명시한다. 기존 저장·동기화 경로를 변경하지 않는다.
사진 저장소와 측량 관계 저장소의 명칭을 반환하는 것이 실제 업로드/동기화 연결 완료를 뜻하지 않는다.
완료 필수 설정은 현재 정의값이며 기존 클라이언트의 저장을 차단하지 않는다.

지자체 이름으로 프로젝트 그룹을 추측하지 않는다. 현재 프로젝트에 authoritative 지자체 코드가
없으므로 그룹을 명시적으로 선택한다. 그룹 소속 프로젝트에는 그룹 항목이 자동으로 상속된다.
중앙 전 테넌트 공통 표준 배포는 이번 범위에 포함하지 않는다. 각 tenant 정의를 중앙 화면에서 관리한다.

## 왜 3개 테이블이 필요한가

확인된 meta_field_def는 시설물 물리필드, profile_field는 공통 프로필+물리필드 조합이다.
프로젝트 전용 항목/사진 구성과 공통 승격을 기존 키로 표현할 수 없다.
prj.projects.ext나 ops.settings_nodes에 별도 숨은 정의 체계를 만들지 않는다.

추가 대상은 **tenant의 gis schema 세 테이블과 인덱스 네 개**다. 중앙 신규 테이블은 0개다.

| 테이블 | 역할 |
|---|---|
| gis.form_item | 안정적인 항목 UUID, 시설물, 타입, 제한된 config, project-private origin |
| gis.profile_form_item | 기존 profile에 추가 항목 연결 및 완료 시 필수 입력 정의 |
| gis.project_form_item | 기존 project에 추가 항목 연결. 공통 profile 변경 없음 |

DDL: docs/architecture/gis-form-definitions-v1.sql. 테이블 신규 생성만 포함한다.
시설물 컬럼/행, reference group/value, 기존 profile 행을 migration에서 변경하지 않는다.
백필/seed는 없다. 운영에 자동 적용하는 Django migration이나 실행 workflow는 추가하지 않았다.
`ops.attachments` 및 `gis.survey_link`의 schema는 그대로 둔다.

## 검증 및 배포 경계

- 순수 설정 검증과 기존 GIS 회귀 검사. 로컬 GEOS fallback 사용 여부를 결과에서 분리한다.
- 실제 PostgreSQL 검사는 고정 localhost:55440/geoflow_forms_test만 사용하며 opt-in 필수다.
- CI `form-definition-isolation`이 신규 DDL, 프로젝트 격리, 그룹 상속, 승격, 사진 저장소 재사용, code/label을 검사한다.
- 기존 필수 CI 외에 이 CI까지 성공한 정확한 PR head만 병합한다.
- 코드 배포 workflow는 release push 후 기존 production Environment 승인을 기다린다. 승인 SHA와 release HEAD, 운영 diff allowlist를 검증한다. DDL/migrate/pip install/collectstatic은 실행하지 않는다.
- 테이블 적용 전 코드 배포 시 참조코드·기존 프로필 관리만 사용 가능하고 추가항목 화면은 준비 중 메시지를 표시한다. 전체 기능 완료로 보고하지 않는다.

## 운영 DDL 사전 조건 및 복구

AGENTS.md에 따라 정확한 tenant/DDL 적용은 별도 구체적 운영 승인이 필요하다.
승인에는 cheonan_db의 위 세 테이블/네 인덱스, 기존 데이터 변경 0건을 명시한다.
정식 역할에서 최신 구조를 재확인하고 세 테이블 중 하나라도 이미 존재하면 자동 병합하지 않는다.
기존 FK 대상의 타입·권한, 메타데이터 편집 중지, 기존 GIS metadata의 복구 가능한 백업을 확인한다.
SQL 전체를 한 transaction으로 적용한다. 실패 시 rollback한다. 다른 tenant로 자동 확장하지 않는다.

code rollback은 기존 배포 방식으로 이전 SHA를 복원한다. 신규 테이블은 기존 코드가 참조하지 않으므로
자동 DROP하지 않는다. 등록된 정의가 생긴 뒤에는 추가 백업·사용 현황을 확인하고 선택 복구한다.
물리 시설물·사진·reference 전체를 복원하거나 삭제하지 않는다.

적용 후 중앙 관리자/일반 사용자 권한, 프로젝트 A/B 격리, 그룹 상속과 프로젝트 전용 추가,
공통 승격 ID 보존, 활성 reference, missing-schema 메시지, 기존 QGIS manifest/sync를 확인한다.
실제 운영 상태 및 배포 성공은 CI 통과와 구분한다.

## 플러그인 후속 계약

서버 정의 API가 운영에 적용된 뒤 최신 플러그인 원본으로 작업한다.
기존 Designer 폼은 보존한다. 추가항목은 item UUID와 kind/storage/config를 기준으로 표시하고,
NULL boolean과 false를 구분한다. origin/source 및 required_display를 유지한다.
클라이언트에 그룹명 분기나 코드값을 복제하지 않는다. 저장·사진·관계 및 완료 검증을 서버와 함께
연결하고 QGIS/QField 오프라인 호환을 확인하기 전 강제 규칙으로 활성화하지 않는다.
