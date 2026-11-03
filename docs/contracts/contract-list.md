# 계약 목록·개인 상세필터

## 계약–프로젝트 정책 전환 준비

상태: **사용자 확인된 이름 4건 운영 정정·검증 완료(실행 41587221621). SINGLE/MULTIPLE 기능 구현 완료. 로컬 회귀 82개 통과, PostgreSQL·브라우저 CI 검증 진행 중. 기능 배포·전체 데이터 전환은 아직 미실행.**

- 기존 `Project.contract_id`와 UUID를 유지한다. 별도 매핑/그룹 모델이나 프로젝트 계약금액 복사는 추가하지 않는다.
- `Contract.ext.project_mode`는 `SINGLE`/`MULTIPLE`만 허용하며 기존 ext 항목을 보존한다.
- 신규 SINGLE 계약은 기존 UX대로 실제 프로젝트 1개를 원자적으로 생성한다. MULTIPLE 계약은 계약만 생성하고 프로젝트 메뉴에서 추가한다.
- SINGLE의 이름 원본은 Contract.name이다. 계약명 편집 및 MULTIPLE→SINGLE 전환 시 서버에서 프로젝트명을 맞추고 프로젝트 화면의 이름은 읽기 전용으로 둔다. MULTIPLE에서는 프로젝트명을 독립 관리한다.
- SINGLE 개수 제한과 계약별 코드 순번은 계약 행 잠금 안에서 검사/배정한다. 신규 코드는 `{contract.code}-{sequence:03d}`이며 삭제 후 번호 재사용 방지를 위한 발급 최댓값을 계약 ext에 보존하는 방향이다. 기존 코드는 감사 후 검토된 항목만 바꾸며 UUID는 보존한다.
- Project.status와 프로젝트 기간을 목록·상세의 수행상태/일정 원본으로 사용한다. 상태 코드는 운영 distinct 값 확인 후 기존 체계를 재사용하며 계약 이벤트를 자동 전환하지 않는다.
- 수정일은 프로젝트 본문 변경 시 갱신한다. 통합 활동일, 손익, GIS/플러그인/Survey 구조 변경은 범위 밖이다.

### 감사와 데이터 변경 경계

`scripts/ops/audit_contract_projects.py`는 활성 테넌트의 계약/프로젝트 개수·연결·이름/코드 변경 예상값·상태·컬럼·FK/UNIQUE/CHECK·인덱스·사용자 트리거를 읽는다. 중앙 조회는 READ ONLY, 테넌트는 REPEATABLE READ + READ ONLY이며 commit/DDL/DML/서비스 재시작을 하지 않는다. 연결 실패·부분 스키마·과다 행은 미검증을 숨기지 않고 중단한다.

`.github/workflows/contract-project-policy-audit.yml`은 PR에서 순수 분석 검사를 하고, release push 또는 명시 실행에서는 기존 `production` 보호 승인 후 감사한다. 로그에는 집계와 고정된 검토 사유만 남긴다. 실제 이름/코드/UUID 및 DB 제약 상세는 공개 인증서 `deploy/contracts/audit-recipient.pem`으로 암호화하여 7일 보관 artifact에 저장한다. 개인키는 저장소/Actions에 넣지 않는다. 감사 결과는 데이터 변경 허가나 자동 실행 명령이 아니다.

기존 복수 프로젝트, 계약 없는 프로젝트, 이름 의미 차이, 변환 충돌, 미인식 코드, 예상 밖 제약/트리거 또는 외부 영구 식별자 사용이 있으면 데이터 변경 전에 보고한다. 프로젝트가 없는 계약도 별도 검토 대상으로 표시한다. 일반 런타임에서 프로젝트 개수로 모드를 자동 판별하지 않는다.

### 코드 참조 영향 조사

| 경로 | 현재 참조와 전환 영향 |
|---|---|
| Web/API·프로젝트 참여자 | URL과 관계는 UUID, 응답 code/name은 표시값. 기존 UUID 유지 |
| QGIS manifest/package·Survey API | `gis/qgis_views.py`는 UUID로 URL/권한을 구성. code는 manifest·다운로드 파일명에 사용 |
| QGIS 로컬 cache | `cache/reuse.py`의 프로젝트 폴더와 `cache/snapshot.py`의 식별 비교는 UUID. 파일명·메타데이터·표시에는 이전 코드가 남을 수 있음 |
| QField package | UUID project_id와 표시용 project_code를 함께 기록. 기존 오프라인 package 재생성/표시 갱신 검증 필요 |
| Finance | 기존 거래 연결은 project_id. `finance_import_views._project`는 이름/코드로 검색하므로 이전 코드를 담은 외부 입력 파일의 호환성 확인 필요 |
| 임시 계약 Sheets export | `scripts/integrations/temp_contract_sheet_sync.gs`에 프로젝트 ID·코드·이름·전체 프로젝트 열이 존재. 코드 변경 후 소비자/수식 영향은 운영 확인 필요 |

저장소 밖 소비자가 코드를 영구 키로 사용하는지는 코드 검사만으로 확정하지 않는다. 운영 감사 및 사용자에게 변경 예정값을 보고하기 전에는 이름·코드를 수정하지 않는다. 향후 구현에서는 목록·상세·계약 첫 프로젝트 참조·대시보드·외부 입력을 회귀 검증하고 이 절의 구현/검증/배포 상태를 갱신한다.

### 운영 감사 결과와 승인된 이름 정정

2026-11-03 감사 실행 `41565594398`은 활성 테넌트 3개의 계약 775건과 프로젝트
775건을 확인했다. 모두 계약당 프로젝트 1개이며 연결 없는 프로젝트, 코드 중복,
새 코드 변환 충돌은 없었다. 이름 불일치는 13건(빈 이름 2건 포함), 기존 코드는
C 접두사 47건·숫자형 726건·빈 값 2건이다. 프로젝트 수행상태 실제 값은
`complete`, `active`, `pause`, `canceld`, `planned`, NULL이다. `pause` 등의 의미는
프로젝트 기존 참조값과 대조해야 하며 계약 이벤트 의미를 그대로 적용하지 않는다.
주 테넌트에는 Project→Contract 물리 FK와 Project.code UNIQUE가 있으나,
다른 두 테넌트에는 해당 제약이 없다. contract_id UNIQUE나 사용자 트리거는 없었다.

사용자는 의미 차이가 의심된 4건 모두 **현재 계약 연결이 맞으며 계약명으로 통일**하도록
확인했다. 이번 선행 정정은 이 4건의 `Project.name`과 `updated_at`만 변경한다.
UUID·계약 연결·코드·상태·일정·금액·ext 및 다른 9건의 불일치는 이 실행에서 변경하지 않는다.
다른 이름 정리 및 코드 변환은 전체 정책 전환 단계로 남긴다. 사용자는 기존 숫자형 프로젝트코드를 외부 고정 식별자로 사용하지 않는다고 확인했다.

현재 활성 `security_views.contract_create`는 최초 생성 때 계약명을 복사하지만,
`views_contracts.contract_detail_page`의 편집 저장은 Contract만 저장한다.
프로젝트 목록·상세는 계약명을 표시해 저장된 Project.name 차이가 화면에 숨겨질 수 있다.
이는 불일치가 유지되는 코드상 원인이다. 과거 변경 이력을 확보하지 못했으므로
각 4건의 최초 발생 시점이나 실제 입력·가져오기 경로는 확정하지 않는다.

4건 정정 실행 `41587221621`에서 matched=4, updated=4, verified=4를 확인했다.
코드·UUID·연결·상태·일정·금액은 보존됐고 서비스 재시작은 없었다.
완료된 일회성 정정 도구·workflow·대상 manifest는 제거한다. 실행 소스와 검증은 PR #456에 보존되며,
호스트 암호화 백업은 `/var/tmp/geoflow-confirmed-project-names/41587221621-1.cms`다.

### SINGLE/MULTIPLE 구현

- 원본과 관계: 기존 `ctr.contracts` → `prj.projects.contract_id` 1:N, UUID 유지, Project 금액 필드 없음.
- 공통 저장 규칙: `services/contract_project_pair.py`. 계약 이름·모드 저장, 프로젝트 생성·본문 편집은
  같은 계약 행을 먼저 잠근다. SINGLE은 최대 1개, 이름은 계약에서만 바꾼다. MULTIPLE→SINGLE은
  1개 이하이고 확인 체크가 필요하다. SINGLE→MULTIPLE에서 기존 이름은 유지한다.
- `Contract.ext.project_mode`와 `project_sequence`만 정책에 사용하고 다른 ext 항목은 잠금 후 읽은 값을
  보존한다. 런타임에서 프로젝트 수로 모드를 추론하지 않는다. 미초기화 계약의 생성은 차단한다.
- 신규 SINGLE 계약은 기존 원자적 생성 wrapper를 유지한다. MULTIPLE은 자식 없이 계약만 생성한다.
  프로젝트 목록/계약 상세의 생성은 동일 `/projects/new/` 화면이다. 계약은 필수, 코드·연결 계약은
  프로젝트 편집에서 바꿀 수 없다. 이름 중복은 Unicode/공백/대소문자 정규화 후 확인 체크를 요구한다.
- 생성 권한은 tenant context + projects.view + projects.edit + contracts.view + 전체 프로젝트 편집 역할이다.
  프로젝트 코디네이터/개별 프로젝트 담당자의 편집권한은 새 전역 프로젝트 생성 권한으로 확대하지 않는다.
  기존 편집은 해당 프로젝트 scope 검증을 유지한다. 계약 상세 목록/업무범위도 프로젝트 조회 범위를 적용한다.
- 순번은 ext 발급 최댓값과 현재 계약의 발급 코드 최댓값 중 큰 값+1. 삭제 후 재사용하지 않는다.
  `{contract.code}-{sequence:03d}`를 생성하고 충돌 시 저장을 차단한다. 계약번호를 나중에 편집해도
  이미 발급한 프로젝트코드는 자동 재번호하지 않으며 이후 발급만 현재 계약번호와 누적 순번을 사용한다.
- `Project.status`를 수행상태로 표시한다. 기존 코드 planned/active/pause/complete/canceld/NULL을 보존한다.
  테넌트 `project.status` 설정이 있으면 표시명·선택지에 우선 적용하고 기존 저장값도 보존한다.
  미설정 시 기존 공통 상태표의 표시명(계약전/진행/중지/완료/취소)을 사용한다. 계약 이벤트 상태와 연결하지 않는다.
- 목록·JSON·상세·대시보드 프로젝트 건수/마감일은 Project 이름/상태/기간을 사용한다.
  상세 DOM을 계약정보만으로 재구성하던 `project-contract-card-parity.js`와 전역 로드를 제거한다.
  계약 업무단계는 상세에 별도 표기한다. 수정일은 본문 저장·SINGLE 이름 동기화 시 현재시각으로 갱신한다.
  목록 기본 정렬은 수정일(없으면 생성일) 내림차순, 동률 UUID순이며 브라우저는 같은 수정일 컬럼을 사용한다.
  담당자는 기존 활성 프로젝트 관리자이며 directory.view 없이는 이름을 숨긴다.

### 기존 데이터 전환·배포

스키마 migration은 없다. `scripts/ops/activate_contract_project_policy.py`는 감사 당시의
3개 테넌트·775개 1:1 관계와 이름/코드 스냅샷을 해시 manifest로 다시 대조한다.
4건 정정 후 남은 이름 불일치 9건, 코드 775건을 계약명 및 계약번호-001로 전환하고
775개 계약에 SINGLE/발급순번=1을 설정한다. 기존 UUID·상태·일정·금액·설명·연결·다른 ext 값은 보존한다.
C 문자를 단순 제거하지 않고 검토된 연결 계약의 코드로 새 표시 코드를 산출한다.

`phase4-workboard-production-deploy.yml`의 첫 도입 배포에서만 전환한다. 기존 production 보호 승인,
정확한 최신 release SHA 확인, 코드 롤백을 유지한다. 이전 앱의 쓰기를 막도록 전환 직전에 서비스를
잠깐 중지하며 실패 시 이전 코드와 서비스를 복구한다. 각 테넌트 테이블 잠금 아래 모든 대상 검증을
먼저 수행하고, 변경 전 전체 계약/프로젝트 레코드를 호스트 0700/0600 디렉터리에 암호화·fsync한 뒤
갱신한다. 백업 경로는 `/var/tmp/geoflow-contract-project-policy/<run>-<attempt>.cms`다.
DB 제약/독립 인덱스 변경·사용자 트리거·스냅샷 변화·복수 프로젝트·연결 누락은 배포를 중단한다.

모든 테넌트의 갱신/검증 성공 후 커밋하지만 여러 DB에 분산 원자성은 없다. 중간 커밋 실패 시 배포는
중단되며 이미 완료된 테넌트와 미완료 테넌트를 구분해 재실행할 수 있다. 재실행은 동일한 전/후 상태만
허용한다. 코드 롤백은 데이터를 되돌리지 않는다. 데이터 복원은 암호화 백업과 현재 값을 비교한 별도
검토 작업으로 수행한다. 전환 이후 새 업무 데이터가 있으면 과거 snapshot을 강제로 재적용하지 않는다.

기존 GIS/재무/참여자 UUID 연결은 바꾸지 않는다. QGIS/QField 기존 오프라인 패키지의 표시 코드에는
옛 값이 남을 수 있으므로 재다운로드 시 새 표시값을 확인한다. 외부 플러그인 코드/패키지를 수정하지 않는다.
실제 운영 로그인 UI·오프라인 단말 확인은 별도 확인사항이다.

검증: 격리 정책/권한/화면 테스트, 기존 업무 회귀, PostgreSQL 동시 생성·잠금·원자적 실패·
데이터 전환·대상 외 값 보존·멱등 재검증을 수행한다. 운영 배포 완료는 보호 배포 결과 확인 후 기록한다.

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
계약 목록은 업무단계 배지 오른쪽 위에 **표시 중인 이벤트 기록 수**를 표시한다.
같은 종류를 여러 번 입력해도 각 기록을 센다. 0건이면 숫자를 숨기고 중지(`suspend`)
이벤트가 표시 중이면 `Ⅱ`를 함께 표시한다. 전체 누적 이력/미확인 건수는 아니다.
기존 표시 기간과 건별 조회 권한을 통과한 기록만 집계하며 종류명은 중복 제거해 도움말과
검색용 데이터에 보존한다. 상세필터도 같은 표시와 검색 데이터를 재사용한다.
중지 검색은 **표시 중인 이벤트 / 포함 / 중지**로 한다. 이는 기존 배지 표시 정책에 맞춘
검색이며, 만료된 중지 이력 또는 현재 중지 여부를 새로 산정하지 않는다.

## 기본 목록

- 평상시 기존 목록·상태 탭·전체보기(과거 완료)만 표시하며 Column Search 행은 숨긴다.
- `필터` 버튼은 기본 목록 검색창 바로 왼쪽에 배치하고 검색 행만 표시/숨김한다. 값과 `column.search()`는 유지한다.
- 기본 검색: 계약번호·계약명·상태·시작일·종료일·계약종류·금액·거래처·계약자.
- 계약 기본 정렬은 코드 내림차순, 상세 이동·배지·과거 완료 필터·overview 링크는 유지한다.
- 사용자 요청에 맞춰 **계약에만 10/25/50**을 적용했다. 이전 구현은 15/30이었으며 다른
  목록은 그대로다. `gf-list-core.js`의 `orderCellsTop`은 숨겨진 검색행의 헤더 정렬 충돌을 피한다.
- 기존 계약종류 표시명 치환은 현재 페이지 밖의 모든 DataTables 행에 적용하고 캐시를 갱신한다.

## 상세필터와 선택 계산

진입은 기본 목록의 3점 메뉴 → `계약 생성` 바로 아래 `상세필터`다. 추가 탭도
`계약 목록` 탭으로 돌아와 같은 메뉴에서 연다. 기존 상세필터 탭의 조건과 결과는 유지한다.

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
  PostgreSQL 16 호환 도구가 없으면 공식 PGDG 서명(고정 fingerprint)을 검증한 client-16/libpq
  패키지를 백업 전용 디렉터리에 다운로드·압축 해제한다. 시스템 패키지 설치, 전역 apt 설정,
  기존 libpq 교체, DB 서비스 생성은 하지 않는다. 전용 wrapper로만 라이브러리 경로를 적용한다.
  준비와 백업 검증이 실패하면 DDL 없이 중단한다. 실제 분리 클라이언트의 백업·적용은 CI에서 검증한다.
