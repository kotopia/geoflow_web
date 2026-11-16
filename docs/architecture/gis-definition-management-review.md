# GIS 업무정의 중앙 관리 — 구현 전 구조 검토

검토일: 2026-09-16. 소스 기준: `d8b0ee7acf2ed2956b388c8a3afccd2f20c4685e`.
상태: 소스 조사 및 읽기 전용 운영 조사 도구 준비. **화면 구현·등록·배포는 미완료**.
운영 DB 조사 결과가 아직 없으므로 아래는 실제 운영 schema 존재를 보증하지 않는다.

## 이미 있는 구조와 재사용 경계

| 요구 | 확인한 기존 구조 | 재사용 방법 / 확인할 점 |
|---|---|---|
| 중앙 업무 분류 | `control/catalog/models.py`, 중앙 `catalog.category_*` | L1–4 업무와 옵션. GIS 시설물 필드/사진 정의를 업무 옵션으로 섞지 않는다. |
| 테넌트 선택 | 중앙 `groups`, `group_db_config`; 기존 Secrets Manager resolver | 인증 테넌트 그룹과 아산시/하수도 같은 GIS 업무 그룹은 다른 개념이다. 회사 그룹을 새로 만들지 않는다. |
| 시설물·필드 정의 | tenant `gis.meta_feature_type`, `meta_field_def` | 물리 필드의 label/type/widget/code 연결은 유지. 필드 정의 등록이 곧 물리 컬럼 생성은 아니다. |
| 공통 그룹 구성 | tenant `gis.profile`, `profile_feature`, `profile_field` | municipality/시설물/필드 구성을 재사용. 공통 설정 변경 시 공유 사업 영향 확인. |
| 프로젝트 적용 | tenant `gis.project_profile` | 현재 프로젝트당 하나의 profile. 기존 그룹 상속과 프로젝트 전용 추가를 동시에 표현하는 override 구조는 이 DDL에 없다. |
| 업무에 따른 레이어 | `gis.scope_binding`, `capability`, `capability_feature`, `prj.scope_item` | 기존 Layer Plan을 유지. 하수 항목을 상수 시설물까지 적용하지 않는다. |
| 참조코드 | tenant `gis.ref_code_group`, `ref_code_value`; `reference_catalog.py` | 기존 저장소 유지. 중앙 UI를 만든다고 중앙 DB로 복제하지 않는다. 사용 중인 코드는 비활성화하고 기존 저장값을 보존한다. |
| 사진 파일 | `geoflow_ops.models.Attachment`, tenant `ops.attachments` | entity_type/entity_id/purpose/object_key/meta와 파생파일 연결 존재. GIS 객체 권한·project 소속·코드별 목적·오프라인 동기화 연결은 별도 확인해야 한다. |
| 관련 측량 | `gis.survey`, `survey_link` | 이미 있는 시설물-측량 관계 재사용. 범용 관계 기능으로 무조건 확장하지 않는다. |
| 희소 속성 | 시설물 `ext_data` | 제한적 후보. 현재 manifest/변경수집/충돌처리/타입 검증에 확장 정의를 연결해야 하며 JSON에 넣는 것만으로 완료되지 않는다. |
| 중앙 화면 등록 | `control/urls.py`, `control/templates/control/partials/sidebar.html` | `require_central_admin`을 서버에서 강제. 메뉴 숨김만으로 권한을 대신하지 않는다. |

근거: `docs/architecture/gis-schema-foundation.sql`, `gis-scope-capability-v0.1.sql`,
`gis-data-model.md`, `geoflow_ops/gis/layer_plan.py`, `gpkg.py`, `reference_catalog.py`,
`control/catalog/models.py`, `geoflow_ops/models.py`.

## 확인된 빈틈

현재 `meta_field_def`는 feature별 물리 필드명으로 유일하고 `profile_field`는
profile+field 조합이다. 따라서 아래 기능은 기존 테이블 편집 화면만 추가해 완성할 수 없다.

- 공통 profile을 건드리지 않는 프로젝트 전용 추가.
- 동일 항목 ID를 유지하는 프로젝트 전용 → 그룹 공통 승격.
- 필수 표시와 완료 시 필수 입력의 분리 및 상속 제한.
- 사진 최소/최대 수, 업무범위별 조건 및 관련 객체 유형.
- 중앙 공통 정의와 tenant별 실제 저장소의 버전/적용 이력.

없는 테이블을 가정하거나 별도 EAV 저장소를 먼저 만들지 않는다. 운영 catalog 조사에서
동등한 기존 구조가 있는지 확인한 뒤 최소 추가 metadata만 설계한다. 사진 파일 저장소,
참조코드 값 저장소, 시설물 테이블은 새로 만들지 않는 방향이다. 실제 schema 확장이
필요하면 변경 이유·소유 DB·영향·migration·rollback을 구체화한 뒤 적용한다.

## 중앙 화면과 프로젝트 화면 구성

중앙 메뉴는 **GIS 업무정의**로 등록한다.

| 화면 | 주요 내용 |
|---|---|
| 업무 그룹 | 지자체·분야·대상 시설물, 상속 항목, 적용 사업 수, 변경 영향 |
| 항목 | 속성/사진/관계 구분, 안정적인 항목 ID, 타입·저장 방식·참조코드, 사용 현황 |
| 참조코드 | 기존 그룹/값 등록·수정·비활성화, 저장 code와 표시 label 분리 |
| 적용 현황 | 공통/사업 전용 출처, 버전, 승격 검토, 변경 미리보기 |

프로젝트 GIS 상세의 **폼 및 첨부 구성**은 상속 항목과 프로젝트 추가 항목을 나란히
표시한다. 프로젝트에서 아산시/하수도 분류 아래에 추가해도 공통 그룹 정의를 수정하지
않는다. 그룹 필수 표시 항목은 제거할 수 없고, required-at-completion은 별도 설정이다.
추락방지시설의 미조사(NULL)와 없음(false)을 구분한다. 공통 승격 시 기존 ID/값을 보존하고
동일 이름만으로 합치지 않는다. 기존 프로젝트의 규칙 변경은 영향 미리보기·버전 적용으로
처리하며 기존 완료 객체를 자동 훼손하지 않는다.

## 필요한 운영 구조 확인

현재 작업 환경에는 VS Code의 `AWS_EC2_Server` SSH 설정·키 또는 운영 DB 연결이 없다.
소스 조회와 이전 배포 성공은 확인했지만 중앙·tenant의 현재 schema는 미검증이다.
이 상태에서 테이블 추가나 운영 배포를 진행하면 사용자의 선행 조건에 어긋난다.

`scripts/ops/inspect_gis_definition_storage.py`는 기존 정식 실행 환경에서 중앙과 명시한
tenant를 각각 읽기 전용으로 조사한다. 애플리케이션 relation 이름과 GIS/catalog 및
기존 첨부·프로젝트 테이블의 컬럼·키 구조만 출력한다. 사용자/시설물/코드 값, 접속정보,
default 표현식, 함수/트리거 본문은 출력하지 않는다. 이 구조 보고서는 데이터·권한·동기화
검증을 대신하지 않는다. 다른 schema에 재사용 후보가 보이면 그 대상만 후속 조사한다.

운영과 연결된 VS Code Codex에 전달할 작업:

1. 운영 checkout을 변경하지 않는 검토 checkout에 이 조사 도구와
   `geoflow_ops/gis/definition_inventory.py`를 준비한다. 기존 scripts/ops 도구도 있는
   동일 release checkout을 사용한다. 현재 동작 중인 서비스 파일을 덮어쓰지 않는다.
2. 기존 정식 서비스 환경·운영 역할에서 아래 명령을 실행한다. 비밀값을 채팅/파일에
   옮기지 않는다. `cheonan`은 현재 확인된 조사 대상이며 아산 사업의 소유 tenant라고
   추정하지 않는다. 아산 사업이 다른 tenant라면 정식 등록에서 확인한 대상도 조사한다.

```sh
PYTHONPATH=. /home/ubuntu/geoflow_stabilized/.venv/bin/python \
  scripts/ops/inspect_gis_definition_storage.py \
  --group-code cheonan --db-alias cheonan_db \
  --output /확인된/비공개/검토디렉터리/gis-definition-storage.json
```

3. 생성된 보고서를 비공개로 전달한다. 기존 결과 파일을 덮어쓰지 않는다.
4. 이번 조사에서 migrate/seed/DDL/DML/배포/재시작은 실행하지 않는다.

이 명령은 저장소 root에서 실행한다. `.env`를 임의로 source하지 않고 기존 정식 환경
로드 절차를 따른다. 실패하면 예외 종류만 출력하며 부분 결과를 성공으로 취급하지 않는다.

## 플러그인 순서

서버의 항목 identity, 공통/사업 전용 규칙, 사진/관계 저장 계약과 최종 해석 API를 먼저
확정한다. 지금 플러그인에 그룹명 분기나 새 코드 목록을 하드코딩하지 않는다. 그 후 최신
플러그인을 받아 기존 Designer 폼을 보존하면서 공통 헤더와 추가 항목 렌더링을 연결한다.

## 검증 범위

조사 도구의 로컬 테스트는 읽기 전용 확인·카탈로그 SELECT·비공개 신규파일·덮어쓰기와
symlink 거부·오류 비밀값 미출력을 검사한다. 테스트 대역을 사용하며 실제 PostgreSQL
실행 또는 운영 조회 성공을 뜻하지 않는다. 중앙 UI와 CRUD, schema migration, 배포는
아직 구현/실행하지 않았다.
