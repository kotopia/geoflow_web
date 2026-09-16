# 중앙 GIS 업무정의 v2 배포

## 승인된 변경

사용자는 중앙 공통 그룹/추가 필드/참조코드/조건 규칙으로 수정 및 배포하고 사용하지 않는
GIS 테이블·컬럼을 삭제하도록 지시했다. GIS 데이터 수정·삭제도 허용했다. 기존 계약·직원·
프로젝트 업무 데이터 및 인증/권한 경계를 변경할 권한으로 확대하지 않는다.

## 구조

- 중앙: gis.definition_group/layer/layer_catalog/field/field_layer/code/group_scope/
  group_layer/group_field/rule/rule_value. 11개 정규화 테이블; catalog.category_node 참조.
- 기존 catalog는 업무분류이며 필드/지역별 규칙·값·의존조건을 담지 않는다. 기존 tenant
  profile/ref는 업체별 물리 메타데이터여서 중앙 공유 원본 역할을 할 수 없다.
- 표준 필드·레이어·활성 참조값은 cheonan_db의 검증된 metadata에서 최초 1회 복사한다.
  catalog UUID는 중앙 원본과 정확히 대조하며 필드 UUID는 이후 재배포 시 보존한다.
- tenant: gis.project_definition(project_id,group_id,additions,private_items). 그룹 UUID는
  중앙 논리 참조, 프로젝트 FK는 로컬. 프로젝트 조회/수정은 기존 권한 + Layer Plan 적용.
- 구 form_item/profile_form_item/project_form_item은 배포 시 존재·행수·의존관계 검사 후
  비어 있는 것만 삭제한다. populated/unknown dependency는 자동 삭제하지 않고 중지한다.
- 기존 meta/profile/ref/시설물 컬럼은 실제 사용 중이므로 삭제 대상이 아니다.

## 적용

보호된 GIS central definition deploy workflow가 정확한 release SHA/diff를 검증하고
코드를 갱신한 뒤 `deploy_gis_central_definitions --apply --backup-dir <운영 백업경로>`를
실행한다. production Environment 승인은 사용자가 직접 수행한다.

중앙 신규 테이블 생성/seed는 단일 transaction. tenant 신규 테이블/삭제도 단일 transaction.
중앙 commit 후 tenant 실패 시 중앙 정의를 유지하고 재시도한다. 중앙은 additive이므로
코드 rollback과 양립한다. 재실행은 기존 central marker/table set을 검증하고 seed를 반복하지 않는다.
기존 정의와 데이터의 초기 snapshot은 Git 밖 소유자 전용 0700 디렉터리/0600 파일에 남긴다.
출력에는 비밀/운영 행/연결 문자열을 포함하지 않는다. DB 작업 실패 시 코드는 이전 SHA로 복구한다.

코드 rollback은 중앙 테이블을 자동 삭제하지 않는다. 삭제 대상 구 테이블은 빈 테이블뿐이다.
이전 코드의 추가항목 기능은 schema-pending 상태로 돌아가며 기존 GIS 저장/동기화는 유지한다.
기존 구 테이블이 필요하면 전 버전의 gis-form-definitions-v1.sql을 정확히 검토해 재생성한다.

## 검증

PostgreSQL CI: 그룹→범위→레이어→필드, 유형없음/레이어없음, 필드·코드 CRUD,
참조 FK, 다른 필드 코드 오연결 거절, 조건 순환 거절, 표준필드 보호,
프로젝트 격리/레이어 제한, 빈 legacy 삭제·재실행·외부 의존관계 차단.
DB-free GIS regression 및 실제 원격 heredoc bash 구문 검증을 유지한다.
배포 후 서비스 restart/local login/public HTTPS 200을 검증한다.

## 기능 경계

중앙 정의 관리 및 기존 형식의 참조코드 API 연결 범위다. 추가 필드의 실제 입력 UI,
관계형 하위 기록 저장, QGIS/QField 조건부 위젯은 별도 클라이언트 통합이 필요하다.
완료필수/연결규칙은 정의로 반환하며 기존 클라이언트 저장을 새 규칙으로 차단하지 않는다.
관리 화면에서 사용 중인 코드 삭제는 연결된 모든 tenant의 읽기 검사가 성공해야 한다.
필드 타입 변경은 기존 코드가 있으면 거절하고, 표준필드 구조는 이 화면에서 수정하지 않는다.

## 그룹 저장 오류 / VWorld 배경지도 보완
- Django raw cursor의 JSONB 문자열을 읽을 때 역직렬화한다. 기존 JSONB 행과 스키마는 유지한다.
- 그룹 전체 항목 표시와 개별 항목 연결을 지원하며 실행 API는 프로젝트 Layer Plan으로 제한한다.
- 배경지도는 VWorld WMTS Base로 변경한다. 운영 환경의 `VWORLD_API_KEY`가 필요하다.
  키 값은 저장소에 기록하지 않는다. 발급 서비스 도메인은 실제 서비스 도메인과 일치해야 한다.
- 배포 전 키 설정 확인, 배포 시 collectstatic, 로그인 검사 및 지도 타일 실응답을 확인한다.
- DB 마이그레이션은 필요 없다. 이전 버전으로 코드 복귀 가능하다.
