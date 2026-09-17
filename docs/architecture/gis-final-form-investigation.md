# 중앙 GIS 동적 입력폼 조사 및 최소 변경 설계

## 조사 상태와 범위

2026-09-17. 코드 기준 `f0974400` (`release/stabilized-deploy`). 첨부 1 → 첨부 2 →
최종 작업 착수 지시 순서로 적용한다. 플러그인은 제공된 1.1.2 설치 ZIP을 조사했다.
Windows의 workspace-backup.zip은 이 작업 환경에 제공되지 않았으므로 그 내용을 확인했다고 주장하지 않는다.

**현재는 코드/DDL 조사 결과다. 실제 운영 DB 조사는 보호된 읽기 전용 실행을 준비한 상태다.**
아래 변경 방향은 운영 DB 관측과 대조한 후 확정한다. DB 조사 전에 모델/API/UI 구현을 시작하지 않는다.
새 Form Definition 시스템, 별도 필드 원본, 멀티 그룹, 사진/관계형 저장 모델은 만들지 않는다.

## 현재 구조와 변경 분류표

| 항목 | 현재 구조 | 분류/재사용 | 부족한 정보 | 최소 수정 방향 | DB 변경 | API 변경 | UI 변경 |
|---|---|---|---|---|---|---|---|
| 중앙 catalog | `catalog.category_node`, parent/closure/facet 등; 중앙 정의는 L2 참조 | A | 실제 바인딩·활성 상태 확인 | 기존 업무유형 탐색 재사용 | 없음 | context 노출 | 필터 재사용 |
| 표준 레이어 | tenant `meta_feature_type`; 중앙 `definition_layer` 및 `definition_layer_catalog`는 초기화된 공유 정의 | A/B | 중앙에는 geometry/active/physical table 정보가 없음 | 기존 원본과 연결해 표시; 새 레이어 원본 금지 | 실제 누락 확인 후 기존 컬럼/메타데이터 보완 | layer context | 표준 관리 탭 |
| 표준 필드 | tenant `meta_field_def`; 중앙 `definition_field.source_layer + physical_name` | A/B | 중앙 초기화 시 widget/required/type 정보 일부 손실 | 기존 중앙 필드에 부족한 폼 메타데이터만 확장, 물리 스키마와 대조 | 기존 필드 확장 후보 | 통일 fields | 표준 목록/편집 |
| Alias/Label | tenant `meta_field_def.label`, 중앙 `definition_field.label` | A | 양쪽 값 차이 확인 필요 | 중앙 label 재사용; 별도 alias 원본 만들지 않음 | 신규 alias 컬럼 불필요 | label 사용 | 표시명 편집 |
| DB Data Type | `meta_field_def.data_type`, 실제 `information_schema.columns`; 중앙 `kind` | B | 코드 필드를 text로 바꾸고 timestamp를 date로 축약하는 초기화 | 실제 schema type과 의미형 datatype 대조, widget과 분리 | 기존 필드 확장/정정 | data_type + storage schema | 읽기 전용 DB 정보 |
| Widget | tenant `meta_field_def.widget_type` 존재; 중앙에는 없음 | B | 중앙 편집·확정 widget 없음 | 기존 중앙 필드의 폼 metadata로 승격, 개별 필드명 분기 금지 | 기존 컬럼/metadata 추가 | widget_type | 공통 widget 선택 |
| Required/Readonly/Visible | tenant `required_default`; `profile_field.required/editable/visible/enabled`; 중앙 group_field.required | A/B | 중앙 기본값·override 표현 부족 | 원본 값을 재사용하고 중앙 적용 우선순위 명시; 서버 권한을 override하지 못함 | 기존 metadata 확장 | 최종 flags | 기본/override 편집 |
| 그룹 | `definition_group/scope/layer/field` | A/B | 필드별 순서·필수 외 override 부족 | group_field에 허용된 metadata patch만 확장 | 기존 연결 확장 후보 | resolver 합성 | 그룹 override |
| 추가필드 | 중앙 definition_field; field_layer 연결 | A/B | 표준 필드와 같은 폼 metadata 부족 | 같은 필드 저장소·validator 사용, provenance만 구분 | 기존 필드 확장 | 동일 fields | 현재 CRUD 확장 |
| 참조코드 | 중앙 definition_code(id,field_id,code,label,sort_order) | A/B | 응답에서 UUID 누락, 중앙 enabled 없음 | 직렬화에서 id 보존; 상태는 현재 전부 true 또는 기존 테이블 상태 확장 중 실제 요구에 맞춰 확정 | 상태 저장 필요 시만 확장 | UUID/code/label/order/enabled | 기존 필드→코드 관리 |
| 연결규칙 | definition_rule(source_field/source_code/target_field), rule_value(code_id) | A/B | resolver가 필드 존재만 확인, layer 문맥과 실행·서버 검증 부족 | 기존 UUID 관계 유지; 같은 context에서 해석·검증 | 우선 신규 표 불필요 | 완전한 code UUID 관계 | 기존 규칙 편집 유지 |
| 프로젝트 적용 | tenant project_definition(project_id,group_id,additions,private_items) | A/B | 독립적인 필드별 override 없음 | 단일 group 유지, 기존 행에 override JSON 추가 후보 | 기존 테이블 확장 | project context/최종 합성 | 기존 프로젝트 설정 확장 |
| 표시순서 | field.sort_order + group_field.sort_order; profile sort_order | A/B | 프로젝트 override 및 표준 전체 합성 없음 | 기본→기존 profile 적용 검토→group→project; 최종 정렬 서버에서 수행 | order 테이블 불필요 | 최종 order | 순서 편집 |
| Layout/Component | 현재 중앙 별도 구조 없음 | B | section,row,column,colspan,width ratio,조건,component slot | 기존 필드/레이어의 선언적 JSON metadata로 수용 우선 | JSON 확장 후보; 새 표 불필요 | layout/components | 검증된 입력 편집 |
| Final Definition | central_definitions.resolve + 기존 form-definition API | A/B | 현재 선택된 필드 위주, 표준 전체·context·overrides 미완성 | 기존 resolver/API 확장 | 위 metadata 외 없음 | 기존 endpoint 확장 | 최종 미리보기 검토 |
| 변경감지 | 응답 payload SHA256 revision, version=gis-form-v2 | A/B | context/metadata 포함 및 결정적 순서 보장 필요 | 기존 content hash 재사용; 스키마 버전과 내용 revision 구분 | 새 version 표 불필요 | metadata 변경 모두 hash 반영 | 필요 시 revision 표시 |
| 구 폼 저장소 | form_item/profile_form_item/project_form_item 폐기 경로 존재 | C 후보 | 실제 존재/의존관계 확인 필요 | 조사 후 미사용이면 제거; 이름만 보고 삭제 금지 | 존재/미사용 확인 후만 | 구 경로 정리 | 없음 |
| 사진/관계형 | kind 및 storage 표식, relation.definition_only=true | A/B | 실행·저장 계약 없음 | 미지원 component capability를 명시, 이번에는 저장 구현 제외 | 신규 photo/child 표 없음 | 확장 가능한 component 슬롯 | 배치 정의까지만 |

A: 그대로 재사용. B: 기존 구조 확장. C: 중복/미사용 확인 후 통합. D: 현재까지 새 테이블의 필요성은 확인되지 않았다.
D의 판단은 실제 DB 검사 후 확정하며, 위 JSON 확장 후보도 이미 동등한 정보가 있으면 중복 추가하지 않는다.

## 반드시 확인할 질문의 답

1. **표준 Layer 원본**: tenant gis.meta_feature_type가 물리 테이블·geometry·활성을 가지고,
   중앙 definition_layer는 최초 bootstrap 때 이를 옮긴 공유 정의다. 코드 registry도 지원 레이어를 제한한다.
   현재 이중 경로를 새 원본으로 덮지 않고 중앙 authoring / tenant runtime 역할을 정리해야 한다.
2. **표준 Field 원본**: tenant gis.meta_field_def와 실제 시설물 컬럼. 중앙 definition_field는
   source_layer/physical_name으로 표준 필드를 표시한다. 실제 DB 불일치 검사가 필요하다.
3. **Alias**: 기존 label 두 곳을 재사용한다. 새로운 alias 전용 테이블은 필요 없다.
4. **Data Type**: 실제 PostGIS column type/length/precision/null/default가 물리 저장 기준이다.
   meta_field_def.data_type를 대조하고 중앙 kind만으로 VARCHAR/INTEGER 여부를 추정하지 않는다.
5. **Widget 위치**: 기존 tenant widget_type를 조사한 뒤 중앙 definition_field의 metadata에 통합하는 것이 자연스럽다.
   추가/표준이 같은 경로를 사용하며 Qt 클래스명 대신 의미형 widget을 저장한다.
6. **Required/Readonly/Visible**: 기존 profile_field 등에 존재한다. 신규 규칙으로 권한을 느슨하게 만들지 않는다.
7. **Display Order**: 기본/그룹 순서는 재사용 가능. 프로젝트 override 표현만 보완하면 별도 순서 모델은 필요 없다.
8. **Layout**: order만으로 폭/행은 표현 불가. 선언적 JSON 확장으로 충분한지 검증하며 새 layout 표부터 만들지 않는다.
9. **Code UUID 누락**: central_definitions.resolve 및 reference_payload의 values 투영에 id가 빠진다.
   플러그인 api/references.normalize_catalog도 UUID/rules를 버린다. 서버와 후속 플러그인 양쪽 수정이 필요하다.
10. **기존 API 사용**: `/gis/projects/<uuid>/api/form-definition/`를 확장 가능.
    layer/catalog 선택 파라미터는 Layer Plan 권한 확인 후 필터하며 데이터 접근범위를 넓히지 않는다.
11. **신규 Table**: 코드 조사상 이번 범위에서는 근거가 없다. 실제 DB 결과 전에 필요하다고 확정하지 않는다.

## 기존 API와 QGIS 1.1.2 경로

- project discovery: `/gis/api/qgis/projects/`
- manifest: `/gis/projects/<uuid>/api/qgis-manifest/` — 레이어 필드 및 transport URL 제공.
- package: `.../api/qgis-package/` — GPKG snapshot. `gpkg_snapshot_v2._profile_layer_fields`가
  meta_field_def/profile_field를 합쳐 label/widget/required/editable/visible을 제공한다.
- reference: `.../api/reference-catalog/` — 기존 code group/binding 형식. QField는 별도 인증 경로를 사용한다.
- 저장/동기화: manifest의 changesets/delta 또는 qgis-sync. Profile editable 및 immutable 필드를 서버에서 검사한다.
- 신규 중앙 폼 API는 이미 있으나 1.1.2 설치본에는 소비하는 Form Definition 서비스가 없다.
- `forms/water/contracts.py`: FIELD_MAPS, CODE_GROUPS, widget objectName, MIRRORS, 숨김 필드/상태값.
- `forms/water/registry.py`: 7개 상수도 전용 폼. `ui/form_host.py`: 미등록 레이어는 전용 폼 준비 안내.
- `forms/common/binding.py`: 기존 Designer 위젯 binding이며 `_cde`/특정 이름으로 코드 판단도 한다.
  PhotoProvider/RelationProvider는 NotImplementedError. 이 코드나 리소스는 이번 조사에서 수정하지 않는다.
- `api/references.py`: normalize_catalog는 선택목록을 code/label/sort_order로 축소한다.
  향후 통합 서비스에서 UUID, enabled, rules, revision을 보존해야 한다.
- 사용자 예시 DIA는 실제 컬럼명으로 가정하지 않는다. 설치본은 구경 관련 legacy 매핑도 있어
  실제 표준/물리 필드를 확인하고 예시와 매핑한다. 원본 컬럼을 예시 이름으로 임의 개명하지 않는다.

## 잠정 최소 구현 명세 (운영 조사 후 확정)

- 표준 관리 탭: 업무유형→기존 레이어→source_layer/physical_name 있는 기존 필드.
  물리 type/null/default는 읽기 전용, 중앙 label/widget/flags/order/layout는 폼 관리.
- field 기본 metadata + group_field patch + project_definition override JSON을 합성한다.
  미지정/false/null을 구분한다. 필드 자체 출처(standard/extension)와 적용 출처(group/project)는 별도로 유지한다.
- 기존 profile 제한은 package 및 서버 쓰기 권한과 모순되지 않게 합성한다. 중앙 visible/readonly는 권한 부여가 아니다.
- layout/component/condition은 허용키·타입·범위·field UUID 관계를 검증한다. 실행문자열/eval은 허용하지 않는다.
- reference 선택은 UUID로 규칙 식별, code로 저장, label로 표시한다. numeric code는 실제 datatype로 검증한다.
- rule은 layer context에 있는 source/target에만 적용; 복수 조건의 결합과 기준값 미선택 정책을 명세한다.
  서버 저장 검증도 최종 resolver를 재사용한다. 별도 validation API만 만들고 저장 검증이 됐다고 하지 않는다.
- 기존 content hash에 field metadata, codes, rules, overrides, context, components를 결정적 순서로 포함한다.
  온라인 갱신과 오프라인 정의가 다른 경우 자동 값 삭제 대신 재검증 상태를 제공한다.
- 공통 Header는 worker/date와 created/updated 이력을 구분. workflow 상태와 입력 완성도를 혼합하지 않는다.
- photo/relation_list는 definition-only capability. 실제 사진/child CRUD 및 S3/offline 작업은 후속 단계다.

## 실제 DB 조사 실행과 보호 범위

`GIS form definition read-only inventory` workflow는 테스트 후 production 사용자 승인을 받는다.
검토한 조사 파일 하나를 임시 경로로 전달하고 기존 배포 런타임을 이용한다. 서비스 코드 체크아웃,
마이그레이션, 재시작, 데이터 수정은 하지 않는다. SHA256으로 전달된 스크립트 일치를 확인한다.

- 중앙 및 등록된 활성 tenant를 기존 credential resolver/tenant_cursor(readonly)로 연결.
- PostgreSQL read-only transaction을 확인한 뒤 gis schema/column/FK와 알려진 metadata counts 조사.
- 기존 표준 레이어/필드 label/type/widget/order와 profile flags, catalog L2, 참조코드 coverage 대조.
- 프로젝트는 GIS 구성 집계만 조회. 사용자/직원/계약/프로젝트 본문, 시설물·사진 내용은 읽지 않는다.
- 테넌트/프로젝트/그룹 ID·이름·접속정보·예외 원문 출력 금지. 임의 문자열 default는 값 대신 존재만 표시.
- 조사 실패한 tenant는 실패로 표시하며 전체 완료로 보고하지 않는다.
- 결과는 workflow log의 GIS_FORM_INVENTORY_BEGIN/END 사이 JSON. 운영 관측 결과를 저장소에 커밋하지 않는다.

현재 검증: 로컬 DB 없는 안전성 테스트 5개 통과. 실제 PostgreSQL read-only/정보 비노출 테스트 2개는
CI의 독립 PostgreSQL에서 실행한다. 운영 DB 확인, 구현, 기능검증, 배포는 아직 미완료다.
