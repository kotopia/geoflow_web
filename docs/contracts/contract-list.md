# 계약 목록·개인 상세필터

## 범위와 원본

`/contracts/` → `security_views.contract_list` → `views_contracts.ContractListView`
→ `templates/geoflow_ops/contracts/contract_list.html`을 유지한다. 원본은 선택된 tenant DB의
`ctr.contracts`, `ctr.partners`, `ops.my_org_units`다. 기존 서버 목록은 전체 계약을 SSR하고
DataTables 1.13.4가 클라이언트 검색·정렬·페이지네이션을 담당한다. 원본 업무 데이터나
금액을 필터 저장소에 복제하지 않는다.

접근은 기존 `require_tenant_context` + `contracts.view`다. 현재 계약 목록은 이 권한을
가진 사용자에게 해당 tenant 전체 계약을 제공하며 프로젝트별 제한을 추가하지 않는다.
이번 작업은 이 조회 정책, 등록·상세·재무 권한을 변경하지 않는다. 향후 목록 권한이
바뀌면 상세필터도 같은 서버 목록에서 행을 받으므로 별도의 넓은 조회 경로가 생기지 않는다.

상태는 `contract_workflow` 공통 태그의 이벤트 기반 단계와 표시 중인 이벤트를 재사용한다.
`Contract.status`를 상태의 별도 정답으로 사용하지 않는다. `pause`는 준공이며 중지가 아니다.
중지 검색은 **표시 중인 이벤트 / 포함 / 중지**로 한다. 이는 기존 배지 표시 정책에 맞춘
검색이며, 만료된 중지 이력 또는 현재 중지 여부를 새로 산정하지 않는다.

## 기본 목록

- 평상시 기존 목록·상태 탭·전체보기(과거 완료)만 표시하며 Column Search 행은 숨긴다.
- `필터` 버튼으로 검색 행만 표시/숨김한다. 값과 `column.search()`는 유지한다.
- 기본 검색: 계약번호·계약명·상태·시작일·종료일·계약종류·금액·거래처·계약자.
- 계약 기본 정렬은 코드 내림차순, 상세 이동·배지·과거 완료 필터·overview 링크는 유지한다.
- 사용자 요청에 맞춰 **계약에만 10/25/50**을 적용했다. 이전 구현은 15/30이었으며 다른
  목록은 그대로다. `gf-list-core.js`의 `orderCellsTop`은 숨겨진 검색행의 헤더 정렬 충돌을 피한다.
- 기존 계약종류 표시명 치환은 현재 페이지 밖의 모든 DataTables 행에 적용하고 캐시를 갱신한다.

## 상세필터와 선택 계산

`contract-filters.js`의 `AdvancedFilterController`가 각 AdminKit `nav-tabs` 내부에
SearchBuilder와 결과 DataTable을 만든다. 탭별 DataTable, 조건, 정렬, 제외 ID 집합을 유지한다.
기본 목록 검색·상태·과거완료 UI 필터와 독립적으로, **서버가 현재 페이지에 조회한 계약**을
재사용한다. `overview` 서버 조건으로 들어온 경우 그 범위를 넘어서는 데이터를 받지 않는다.
각 탭에 조회 범위를 안내한다. 과거 완료는 후보에 포함되며 상세조건으로 제외할 수 있다.

- SearchBuilder **1.4.2**, Bootstrap 5 adapter **1.4.2**, DateTime **1.5.2**를 static 자산으로 고정.
  기존 DataTables/Buttons/jQuery/AdminKit를 다시 로드하지 않는다.
- 1.6.0은 기존 코어 1.13.4의 object-valued datetime i18n 호환 오류로 채택하지 않았다.
  1.4.2의 숫자·문자·날짜 및 중첩 AND/OR를 실제 브라우저에서 검증한다.
- SearchPanes는 1차 범위에서 제외한다. SearchBuilder 선택값으로 범주 검색을 제공한다.
- 체크는 최초 전체 포함. 결과에 계속 남는 행의 제외 상태를 유지하고, 사라진 행은 제외
  상태에서도 제거한다. 재등장한 행과 신규 행은 기본 포함이다. 페이지 이동에도 선택 유지.
- 헤더 체크는 **현재 페이지뿐 아니라 조건 결과 전체**에 적용한다.
- `filter-aggregate.js`는 DOM/DataTables와 분리된 순수 계산기다. 원 단위 BigInt 합계로
  큰 누적액의 부동소수 오차를 피한다. 평균은 원 단위 반올림(절댓값 기준 0.5 올림).
  금액 미등록은 선택 건수에는 포함, 합계·평균에서는 제외하고 별도 건수를 표시한다.
  실적 인정액·지분율은 아직 계산하지 않는다.
- 저장은 조건·정렬만 대상으로 한다. 체크 상태는 저장하지 않으며 불러오면 전체 포함.
- 탭의 미저장 조건/정렬/이름이 있으면 닫기 전 확인한다. 같은 이름 저장은 덮어쓰기 확인.
- 로딩·저장 실패·저장소 미준비·빈 결과를 구분한다. 임시 탭 전체의 새로고침 복원은 범위 밖이다.

## 필드 매핑과 데이터가 없는 항목

| UI | 원본 |
|---|---|
| 계약번호 / 계약명 | `Contract.code` / `name` |
| 상태 | 공통 workflow의 `major_label` |
| 표시 중인 이벤트 | 공통 workflow tag의 `active_event_labels` |
| 시작일 / 종료일 | `Contract.start_date` / `end_date` |
| 계약종류 | `Contract.kind` + 기존 tenant vocabulary 표시명 |
| 계약금액 | `Contract.amount` (null과 0 구분) |
| 거래처 | 기존 목록의 `client`/하도급 `sub_client` 표시 규칙 |
| 계약자 | 기존 목록의 `org_unit.label` (우리 회사/지사, 담당부서로 이름 변경하지 않음) |

현재 모델에 독립적인 **지역, 계약일, 담당부서 필드가 없다**. 주소를 지역으로 추정하거나
시작일을 계약일로 바꾸지 않는다. 따라서 ‘지역 = 충남 OR 대전’, ‘계약일 >= ...’ 그 자체는
이번 구현에서 제공하지 않는다. 거래처 문자 조건의 중첩 OR와 시작일 기간으로 엔진을
검증하되, 이를 해당 도메인 필드 검증 통과로 보고하지 않는다.

## 저장 API와 스키마

`/contracts/saved-filters/` GET/POST → `views_saved_filters.py`.
`contract_filter_definition.py`는 버전 1 JSON의 field/operator/type whitelist,
4단계 그룹·30조건·24KB·이름 100자·숫자/ISO 날짜·정렬 인덱스를 검사한다.
조건 JSON은 SQL 실행에 사용하지 않는다. SQL은 정적이며 값은 모두 파라미터 바인딩한다.
CSRF·로그인·계약 조회 권한을 유지하고 응답 캐시는 금지한다.

범용 사용자 preference 저장소는 없었다. 기존 `bid.central_preferences`는 회사별
중앙 입찰수집조건 참조이고 `group_service_menu_settings`는 그룹 서비스 메뉴 설정이므로
재사용하면 소유 범위가 달라진다. 중앙 **`saved_filters`** 한 테이블을 추가한다.

- `id`, 중앙 `user_id`, `group_id`, `module`, `name`, `filter_json`, 생성/수정시각.
- `(user_id, group_id, module, name)` 고유. 같은 이름은 upsert한다.
- 서버가 로그인 bridge 이메일로 중앙 user를 해석하고, 활성 user·그룹·membership 및
  `group_db_config.db_alias`가 현재 tenant와 일치하는지 다시 확인한다.
- 요청 body의 user/tenant/module 식별자는 사용하지 않는다. module은 contracts로 고정.
- 사용자+tenant별 최대 100개. 사용자 행 잠금으로 동시 저장 quota 경쟁을 막는다.
- 중앙 user/group 삭제 시 FK cascade. 개인정보 삭제 뒤 필터 조건을 남기지 않는다.

`control/migrations/0008_saved_filters.py`는 중앙 DB 전용이며 tenant migration은 없다.
원본 계약 backfill은 없다. 코드 rollback 시 저장 조건을 보존하도록 역방향 DROP은 제공하지
않는다. 운영 반영 전 정확한 중앙 migration 적용 승인이 필요하다. 저장소가 없으면 API는
503과 미준비 메시지를 반환하며 기본 목록·임시 상세필터는 동작한다.

## 성능과 확장 경계

이번 상세필터는 **client-side**다. 현재 수백 건 규모의 기존 SSR 결과를 재사용하며 탭별
추가 전체 조회는 없다. 단 기존 기본 목록의 전체 SSR 자체는 변경하지 않았다.
상세필터는 5,000건을 넘으면 부분 결과를 보여주지 않고 명확히 차단한다.
그 이상을 지원하려면 기본 목록과 함께 server-side DataTables/공통 권한 queryset 및
SearchBuilder의 안전한 ORM 변환을 별도 적용해야 한다. 기존 화면을 서버 모드로 전면
전환한 것으로 보고하지 않는다. 선택 합계는 **페이지 로드 시점 값**이며 원본 변경은 새로고침 필요.

## 검증·배포 구분

- `test_contract_filters.py`: JSON 유효성, 사용자/tenant/권한·바인딩·저장소 미준비.
- `test_contract_filters_isolated.py`: 위 테스트와 기존 tenant route 회귀, 운영 설정 없이 실행.
- `rehearse_saved_filters.py`: localhost의 `ci_contract_filters` 전용 PostgreSQL에서 중앙 DDL,
  API 저장/조회/upsert, 사용자·tenant 분리, 비회원·mapping 불일치 거부, 삭제 cascade를 검증하고 rollback.
- `test_contract_filters_browser.cjs`: 실제 Django/AdminKit 템플릿, 기본 숨김/토글, 완료필터,
  복합조건·날짜·OR·이벤트 검색, 선택 제외, 다중 탭, 저장/새로고침/불러오기, PC/390px.
  브라우저 테스트의 저장 HTTP는 fixture이며 실제 저장 API 검증은 PostgreSQL 테스트가 담당한다.
- `test_filter_aggregate.cjs`: 빈 결과·누락 금액·큰 합계·원단위 반올림.
- 기존 dashboard/compact regression과 같은 CI workflow에서 실행하고 화면 캡처를 artifact로 남긴다.

운영 배포 전: CI 전체 통과, 중앙 0008 적용 계획/승인 및 운영 backup 확인,
실제 계정의 저장·불러오기 및 tenant 전환 확인. 구현·테스트 통과는 운영 migration/배포 완료가 아니다.

### 운영 적용 절차 (2026-10-24 배포 지시)

- 기존 production Environment 승인과 정확한 release SHA 검증을 유지한다.
- `activate_saved_filters`는 검토된 0008 blob과 **정방향 단일 migration**만 허용한다.
  처음 적용할 때 서버의 0700 전용 디렉터리에 중앙 DB custom-format 전체 백업(0600)을
  만들고 pg_restore 목록 검증에 성공해야 DDL을 실행한다. 백업/DB 자격정보는 외부 전송하지 않는다.
- 트랜잭션·advisory lock·시간 제한 하에 테이블/기록을 함께 적용하고 열과 고유 범위를 검증한다.
- 기존 `activate_admin_visibility`도 이미 적용된 0007의 후속 migration을 되돌리지 않는다.
- 재시도는 이미 적용된 0008을 읽어 확인하며, 코드 rollback은 새 테이블과 개인 조건을 보존한다.
- 서비스 재시작 및 정적 자산·공개 로그인 정상 응답을 별도 확인한다.

- 백업 도구는 서버 PostgreSQL major 이상인 설치된 pg_dump/pg_restore 쌍을 선택한다.
  도구 없음·버전·인증·접속·권한·디스크 오류는 고정된 분류만 기록하며 원문 오류/접속값은 노출하지 않는다.
  사용 가능한 도구가 없으면 DB 변경 없이 중단하며 OS 패키지를 임의 설치하지 않는다.
