# GIS 선택·심도·방향각 사용 흐름 (1.4.6 후보)

2026-10-30: 배포된 1.4.5를 기준으로 수정한 검토용 후보다. 서버 배포·정식 ZIP 교체·사용자 설치본 교체는 수행하지 않는다. 상세 증거와 제한은 `docs/operations/connector-1.4.6-review.md`에 기록한다.

## 현재 흐름

- 선택 도구 하나에서 클릭/드래그를 QApplication 드래그 임계값으로 구분한다. Shift 추가, Ctrl 해제, Esc 드래그 취소를 지원하며 단일/영역 메뉴와 모드 저장 경로는 제거했다. 기존 QGIS 선택 집합과 단일 폼 연결을 유지한다.
- 일반 아이콘 영역의 심도 버튼은 현재 프로젝트의 쓰기 가능한 지원 레이어에서 2개 이상 선택하면 활성화된다. 편집모드·Survey/H 존재를 활성화 조건으로 쓰지 않는다. NULL만/전체 선택 후 기존 `calculate_feature` 공간검색·단위·정밀도로 계산한다.
- 실제 변경이 필요할 때 편집 버퍼를 시작한다. 결과표는 선택/계산 성공/실제 변경/동일/건너뜀/실패를 구분하고 객체 ID·기존값·계산값·적용 결과·사유를 보여준다. 실패·건너뜀 값은 유지하며 서버 저장은 기존 저장 기능만 수행한다. 폼 note가 숨겨져도 메시지바와 모델리스 결과표에서 결과를 확인한다.
- 공통 `ResultHighlight`를 Survey·심도·방향각에서 사용한다. 결과 행 위치 이동, 변경 객체 전체 보기, 실패/검토 색상, 해제·닫기 정리를 제공한다. 선택이나 속성을 변경하지 않는다.
- 방향각 대상은 중앙 필드 UUID와 레이어 UUID에 연결된 명시적 `capabilities: ["direction"]` 또는 중앙 direction 설정으로 식별한다. 이름 추정은 하지 않는다. 설정 오류가 있어도 필드 오른쪽 자동계산·직접 회전 버튼을 유지하고 툴팁/로그/중앙 정의 진단창에 원인을 남긴다. 일반 필드 액션 숨김 설정은 이 두 버튼을 숨기지 않는다.
- 일반 방향각 아이콘은 선택 0개 비활성, 1개 자동/수동 메뉴, 여러 개 결과 검토 후 일괄 적용이다. 필드 오른쪽 버튼은 같은 콜백을 호출한다. 수동 회전은 각도/심볼 규칙만 검사하고 자동계산 기준선 존재를 요구하지 않는다. 지도 손잡이·다이얼·스핀박스는 미리보기와 동기화되며 취소는 속성/편집 버퍼를 변경하지 않는다.
- 중앙 설정 재조회는 같은 서버·프로젝트의 최신 manifest revision을 읽고 Final Definition과 일치 여부를 확인한다. 지연된 응답과 프로젝트 불일치를 거절한다. 기존 폼에 액션이 없었던 경우에도 refresh 때 생성한다.

## 운영 정의에서 확인된 원인

C26070·C26048의 읽기 전용 API 응답과 QGIS 캐시 모두 revision `06ee99c9c49ecbcedf9e991fec292f7f2797b21e4f5a7ef2a12892e5559bc749`였다. 캐시는 ready였고 레이어/필드 UUID와 물리 ang_dir 존재가 일치했다. 두 프로젝트의 변류시설·기타시설에 `direction: null`, 빈 layout이 전달됐다. 1.4.5는 유효한 direction 설정을 얻지 못하면 필드 버튼 생성 자체를 건너뛰었다. 캐시 유실이나 필드 부재가 원인이 아니다.

변류시설 중앙 필드 `63b76009-fc28-4a7c-b2cf-1fba61e04d2f`는 integer, 기타시설 `502ef46b-9287-4da9-81c2-c085f3ae2090`는 text였다. 이번 서버 변경은 확인된 UUID 두 쌍에 기능 표시만 선언한다. 타입·값·회전 규칙을 바꾸지 않는다. 기타시설 text 계약과 각도 규칙이 정리되기 전 계산/회전은 이유를 표시하며 차단된다. 서버 변경과 후보 플러그인이 함께 검토되어야 하며, 현재 운영 응답에 새 capability가 이미 있다는 뜻은 아니다.

## 기존 1.4.5 조사·검증 이력

아래는 1.4.5 당시의 기록이다. 사용 흐름은 위 1.4.6 설명이 우선한다.


상태: Connector 1.4.5 구현·검증 후보. 운영 배포, 중앙 설정 활성화 및 사용자 설치본 교체는 하지 않았다.
기준 소스: `release/stabilized-deploy` / `30c0d974` (2026-10-28). 기존 최신 Connector는 1.4.4.

## 조사 결과

- `layers/identify.py:IdentifyGeometry`가 활성 관리 레이어를 식별하고 `ui/form_host.py:Main`이 선택 객체와 Dynamic Form을 연결한다. 실제 선택 상태는 QGIS 레이어 및 `layers/selection.py:LayerWorkspaceState`가 소유한다.
- `ui/edit_tools.py:_run_depth()`의 기존 선택 일괄 경로와 `DepthService.apply_to_form()`, `apply_to_features()`, `calculate_feature()`를 그대로 사용한다. 계산식·탐색·NULL·정밀도·서버 저장 계약은 변경하지 않았다. 새 일괄 버튼은 편집 가능한 지원 레이어에서 2개 이상 선택 시 활성화된다. 개별 필드 계산 버튼은 유지한다.
- Dynamic Form 입력은 `DynamicFormBinding`이 원본 대비 비교하고 저장 때 편집 버퍼 및 기존 온라인 changeset에 반영한다. 일반 CRUD·revision conflict·권한 검증은 기존 경로를 유지한다.
- `layers/default_style.py:apply_default_qgis_style()`는 초기 materialization 때 QML의 AllVisualStyleCategories만 적용한다. `geoflow/default_style_applied`가 있으면 사용자 스타일을 보존한다. 따라서 번들 QML과 운영 프로젝트 스타일이 같다고 단정할 수 없다.
- 번들 변류시설 QML의 각도는 `360- 0`, `180 + (360- 0)` 등 상수이고 기타시설 QML은 `360- "angdir"` 등 과거 이름을 사용한다. 기존 활성 필드 `ang_dir`의 부재가 아니라 회전 연결 누락/필드명 불일치 증거다.
- 실제 QGIS 4.2.2 엔진에서 두 QML의 대표 심볼을 복제한 임시 레이어에 `ang_dir=0/90`을 넣었을 때 기존 렌더링은 동일했다. 명시적 새 연결 뒤에는 달라졌다. 검사한 대표 심볼은 SVG가 아니라 SimpleMarker 조합이다. 전체 심볼 속성과 이미지는 `release/1.4.5/direction-style-audit.{json,png}`에 있다.
- 실행 중인 QGIS 창이 없었고 현재 운영 프로젝트 스타일에는 접근하지 못했다. 위 결과는 번들 스타일 검사이며 운영 저장값의 과거 의미를 확정하지 않는다. 운영 확인에는 변류시설·기타시설의 내보낸 QML, 외부 SVG가 있다면 그 파일이 필요하다.

## 사용법

기존 객체 선택 버튼을 짧게 누르면 현재 모드를 실행/해제한다. 길게 누르면 단일 선택/영역 선택 메뉴가 열린다. 펼침 표시·아이콘·툴팁으로 모드를 표시하며 QSettings에 마지막 모드를 보존한다. 영역 모드에서는 사각형 드래그로 현재 작업 레이어만 선택한다. Shift는 추가, Ctrl은 해제, 수정키가 없으면 교체한다. Esc는 진행 중 드래그만 취소한다. 화면 사각형을 캔버스 좌표계에서 만든 후 레이어 좌표계로 변환하여 실제 기하 교차를 판정한다.

방향 설정된 단일 점의 각도 필드 옆에서 방향 조정 또는 자동 계산을 실행한다. 방향 조정은 숫자·스핀·다이얼·지도 손잡이를 동기화한다. 180° 반전은 중앙 설정이 허용할 때만 제공한다. 적용 전에는 원래 심볼 대신 임시 메모리 레이어에서 렌더링하며 운영 속성/서버를 변경하지 않는다. 취소 시 원래 렌더러와 도구를 복원한다. 적용은 QGIS 편집 버퍼로 들어가며 저장은 기존 저장 버튼을 사용한다. 직전 각도 폼 입력과 다른 필드의 임시 입력을 보존하는 실행 취소 명령을 묶는다.

자동 단일 계산의 모호한 후보는 결과 행에서 지도에 선분을 표시하고 후보 하나를 선택한다. 방향각 일괄계산은 2개 이상 선택 시 활성화하며 같은 계산기를 사용한다. 결과표에서 객체 식별값·기존 각도·새 각도·기준선·사유를 확인하고 체크한 결과만 적용한다. 일괄 계산의 모호한 후보는 적용 불가 검토 항목이다. 행 선택으로 객체와 후보 위치에 이동한다. 전체 적용은 한 번에 실행 취소한다. 성공/실패 항목의 기존 값을 임의로 지우지 않는다.

## 중앙 설정과 서버 경로

기존 `gis.definition_field.layout.direction`에 설정을 저장한다. 새 physical field나 영구 객체 관계, migration은 없다. 기존 GIS 업무정의 화면의 표준 필드 편집 아래에 방향 설정 폼을 추가했다. 기존 관리자 권한/transaction/audit 경로에서 `direction` action을 처리한다. 필드가 기존 숫자형 점 레이어 필드인지, 기준선 UUID가 활성 선 레이어인지, 숫자·단위·열거값이 유효한지 검증한다. Final Form의 필드별 `direction`으로 전달하며 프로젝트별 layout override로 계산 규칙이 덮어써지지 않는다.

설정에는 `reference_layer_ids`, `method`(connected/nearest), `distance`, `unit`(m), `offset`, `allow_reverse`, `ambiguity`(review), `zero_axis`(north/east), `positive_direction`(clockwise/counterclockwise), `symbol_offset`, `axis_tolerance`, `tie_tolerance`가 반드시 들어간다. 결과 저장 필드는 해당 중앙 필드 UUID의 기존 `storage.key`를 사용한다. 공통 계산기는 표준명·표시명·지자체명으로 분기하지 않는다.

기준선은 현재 프로젝트에서 materialize된 관리 레이어의 `geoflow/definition_layer_id`와 중앙 UUID를 대조한다. 다른 프로젝트나 범위 밖 레이어를 검색하지 않는다. 표준 `WTL_VALV_PS`/`WTL_PIPE_LM`의 의미는 기존 아키텍처에 있지만 운영 UUID를 추정해 등록하지 않았다. 변류시설·기타시설은 기존 `ang_dir`에 설정을 연결할 수 있으며, 물받이도 동일한 nearest 설정을 사용할 수 있다. 이번 작업은 운영 중앙 설정을 쓰지 않았으므로 이 세 운영 연결은 미활성 상태다.

## 각도·기하 규칙

공통 내부 방위각은 북쪽 0°, 동쪽 90°, 시계 방향의 도 단위다. 저장 전에 계산 보정 `offset`을 더하고, 설정의 0축·증가 방향으로 변환한 뒤 `[0,360)`로 정규화한다. 역변환과 심볼 표현식은 동일 설정을 사용한다. 반전은 저장 각도에 180°를 더하고 정규화한다. 기존 값을 일괄 변환하지 않는다.

새 설정 UI의 기본 선택안은 북쪽 0°/시계 방향이다. 이는 기존 운영값에 대한 단정이 아니다. 실제 심볼의 기본 축은 `symbol_offset`으로 보정한다. 번들의 대표 제수변/지수전 심볼은 0°에서 가로 축이며, 검사에서 +90° 보정 시 저장 0°가 세로, 저장 90°가 가로로 나타났다. 모든 운영 심볼의 기본 방향이 같다는 뜻은 아니다. 사용자 스타일은 QML 확인 후 적절한 보정을 지정한다. 설정된 레이어의 렌더러 복제본에 데이터 기반 회전을 연결하며 복합 심볼의 상대 각도를 유지한다.

점 주변 local azimuthal-equidistant 좌표계에서 미터 거리와 선분을 계산한다. 각 레이어 CRS를 변환하며 도 단위를 미터로 쓰지 않는다. 멀티파트 선을 분리하고 중복 버텍스와 0길이 선분은 제외한다. 끝점에서는 안쪽 첫 유효 선분, 중간 버텍스에서는 인접 선분을 사용한다. 같은 축 허용오차는 명시적 `axis_tolerance`다. 꺾임·다중 접속은 후보를 남긴다. 접속 거리 밖의 중간 선분에 시설물을 임의로 붙이지 않는다. nearest는 각 유효 선분에 투영하여 실제 최근접 선분을 찾고 `tie_tolerance` 내 동률은 검토한다. 평행/직각은 offset 0/90으로 표현한다.

## 저장·실행 취소·회귀 보호

미리보기는 서버 요청과 편집 버퍼 쓰기가 없다. 취소는 다른 필드 입력을 건드리지 않는다. 같은 값 적용은 새 편집 상태를 만들지 않는다. 적용 당시 객체 ID/기하/필드 계약과 기준선 ID·기하·CRS·설정 fingerprint를 검사하고 자동 계산 결과는 실제 온라인 저장 직전에도 재검증한다. stale이면 서버 전송을 중단하고 재계산을 요구한다. 삭제·실행 취소·사용자 재입력으로 더 이상 해당 각도를 저장하지 않으면 pending 검사를 제거한다.

기존 저장 실패 버퍼 보존, 충돌 처리 및 baseline 갱신 코드는 유지한다. 과거 저장/이동 반복 안내의 운영 원인을 이번 작업에서 재현하거나 확정하지 않았다. 새 기능의 무변경·취소·동기화·undo만 별도 회귀 검사하고 기존 저장 성공/실패 회귀 프로그램을 실행했다. 실제 운영 네트워크/객체 이동에서 반복 안내가 해결됐다는 주장은 하지 않는다.

## 검증과 배포 경계

QGIS 4.2.2의 offscreen 실제 엔진/Qt 및 메모리 레이어를 사용한다. 새 계산/선택/미리보기 검사에는 서로 다른 CRS, 끝점/중간/꺾임/다중접속, 최근접/보정, 중복/멀티파트/0길이, 모호함, stale, 무변경, 실제 Dynamic Form 임시값 보존과 undo, 긴 누름/짧은 클릭, 수정키, Esc를 포함한다. 스타일 렌더링 이미지는 별도 확인했다. 중앙 설정 단위검사는 저장 payload·오류·Final Form 전파를 검사한다. 전체 회귀 프로그램 결과는 버전별 regression-results.json과 로그에 기록한다.

운영 프로젝트 GUI에서의 실제 손 드래그, 운영 QML/SVG, 운영 중앙 DB 저장·실제 서버/PostGIS 연계·실제 서버 네트워크 저장은 미검증이다. QGIS 3.x는 직접 실행하지 않았다. 대규모 기준선에서 배치 계산은 동기 실행이므로 응답성 확인이 필요하다. 점 멀티파트와 한 레이어의 여러 동시 방향 결과 필드는 지원하지 않고 오류/미설정으로 차단한다.

배포 순서: PR 검토 및 격리 DB 검증 → 서버 코드 배포 승인 → 운영 QML·기존 각도 의미 확인 → 기존 중앙 필드에 기준선 UUID·보정 설정 → 후보 ZIP 검증/설치 승인 → 사용자 설치본 교체. 어떤 단계도 이 PR 생성만으로 운영 수행된 것으로 간주하지 않는다.

검증 실행 결과: QGIS 회귀 프로그램 18/18, 중앙 정의 단위검사 16/16 통과. 별도 서버 권한 회귀는 로컬 환경의 `channels` 의존성 부재로 실행하지 못했다. 기존 권한 데코레이터와 audit 경로를 유지했으며 CI에서 재확인이 필요하다.

ZIP 실물 검증: 별도 프로필의 QGIS 4.2.2 실행 파일에서 후보 ZIP만 설치하여 101개 모듈 import, classFactory/initGui, 로그인 UI·Dynamic Form 생성, 프로젝트 저장 및 재시작 후 재열기, unload의 2단계를 통과했다. 운영 프로필과 설치본은 교체하지 않았다.

패키지 회귀: 1.4.3·1.4.4의 승인된 런타임 바이트를 보존하여 기존 SHA256/크기를 그대로 재현하고, 1.4.5는 버전별 manifest로 검사한다. 로컬 패키지 검사 19개 통과. 중앙 설정의 실제 저장·Final Form 전파·기존 layout 보존·잘못된 기준선 거절·설정 해제는 CI의 격리 PostgreSQL에서 통과했다(실행 40661808590). 이는 운영 DB 쓰기 검증이 아니다.


### Production deployment JSON cursor compatibility (2026-10-28)

Deployment run 40664386879 failed in the read-only project runtime smoke: the production raw cursor returned field layout as JSON text, while direction extraction assumed a dictionary. The workflow rolled code back and confirmed the service active; stable 1.4.5 publication was not reached. Direction extraction now reuses the central JSON-object parser, preserving the authoritative field settings independently of project layout overrides without changing stored data. A regression reproduces both empty and configured JSON strings, alongside dictionary and null values. The installed Connector 1.4.5 archive is unchanged.
