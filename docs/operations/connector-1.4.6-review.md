# Connector 1.4.6 검토 보고

상태: 미배포 후보. 정식 1.4.5 ZIP과 사용자 default 프로필은 변경하지 않았다. 브랜치 `codex/connector-interaction-flow`, 기준 커밋 `70d1e25a`.

## 산출물

- ZIP: `integrations/qgis/geoflow_connector/release/1.4.6/geoflow_connector-1.4.6.zip`
- 크기: 5,287,367 bytes, 런타임 파일 5,606개.
- SHA256: `cf46e24cf0d47b8d8ab44960d48126d3df76476dacb21da3212d6306ec29c168`
- 버전별 manifest/inventory/package-audit 및 QGIS 회귀 로그를 같은 디렉터리에 보관한다. URL은 미게시 제안값이다. 공개 저장소에 ZIP을 게시하지 않았다.

## 실제 장애 추적

공개 1.4.5 ZIP의 SHA256은 `7657324a0ef173a6c29e55c20e6acdab0289a2be62b0f2a19afd42d2b746c305`로 정식 descriptor와 일치했다. 사용자 로그인 세션에서 읽기 전용 진단 스크립트로 C26070·C26048의 Final Form Definition 및 현재 QGIS 캐시·materialized layer UUID를 비교했다. 토큰·객체 속성은 보고서에 포함하지 않는다.

두 프로젝트 모두 변류시설·기타시설 중앙 ang_dir는 존재한다. UUID 매칭과 캐시 전달은 정상이고 direction은 서버 응답부터 null이다. 1.4.5 register_form_page의 settings 검증/예외 생략 경로가 버튼 부착 전에 중단한다. 일반 필드 액션 표시 설정은 심도 액션에만 적용되어 방향각 누락의 직접 원인이 아니었다. 추가로 기타시설 중앙 semantic type이 text여서 숫자 회전 계약 검증을 통과하지 못한다.

해결은 명시적 UUID capability와 계산 설정을 분리하고, 미설정 버튼도 표시하며 이유를 진단하는 방식이다. 중앙 UUID 등록은 기능 표시이며 기존 각도 규칙 선언이 아니다. 실제 운영 중앙 DB를 갱신하지 않았다. 후보 서버 변경을 적용하지 않은 기존 응답에는 capability가 없으므로 플러그인 ZIP만 교체하는 배포는 완결된 해결이 아니다.

## 검증 범위

- QGIS 4.2.2 실제 엔진/Qt, offscreen: 20개 회귀 프로그램 통과. 계산기 단위 검사 외 classFactory·일반 아이콘 클릭·실제 공간검색·결과표/행 이동/강조·폼 버튼 갱신·미리보기 취소/적용/undo·쓰기 권한 차단을 검사했다.
- 편집 시작 전 2개 이상 선택 버튼 활성화, NULL만/전체 계산에서 changed/unchanged/skipped/failed 분리, Survey 없는 실행 실패 결과와 기존값 보존을 검사했다.
- 방향각 선택/영역/수정키/Esc 및 다른 CRS, 단일·다중 자동계산, 수동 회전의 기준선 독립성은 direction runtime 회귀로 검사했다.
- 최신 manifest/definition revision 일치, 프로젝트 불일치 거절, stale callback 무시와 기존 폼에 버튼 생성·상태 갱신을 검사했다.
- 후보 ZIP만 설치한 별도 프로필에서 실제 qgis-bin.exe --code로 103개 모듈과 classFactory/initGui/폼을 로딩하고, 메모리 객체 UI 시나리오를 실행했다. 운영 로그인/운영 데이터는 사용하지 않았다. 단계별 결과는 `qgis-profile-phase*.json` 참조.

## 운영에서 별도로 확인할 항목

운영 프로젝트의 손 드래그·운영 권한 계정·서버 저장·저장 후 객체 이동 시 안내 반복 여부는 미검증이다. 기존 온라인 저장/폼 라이프사이클 회귀 통과를 운영 검증으로 대체하지 않는다. QGIS 3.x 및 큰 선택 집합에서의 응답성도 미검증이다.

실제 운영 레이어 렌더러/QML/SVG와 저장 각도 0°·90°의 표시 의미는 확정하지 못했다. 필요한 자료는 C26070·C26048 각각의 변류시설/기타시설 **현재 적용 QML**, 외부 SVG가 있다면 해당 파일, 데이터 기반 회전 표현식이다. 이를 임시 레이어에 복제하여 0/90 시험을 해야 한다. 기존 번들 스타일 감사의 상수 회전/angdir 오기 결과를 운영 스타일로 간주하지 않는다.

새 규칙 후보는 `zero_axis=north`, `positive_direction=clockwise`(0° 북, 90° 동)이며, symbol_offset은 실제 심볼 원점 방향을 확인한 뒤 명시적으로 정해야 한다. 이는 새 기능을 위한 제안일 뿐 기존 저장값 의미를 추정하거나 변환하는 설정이 아니다. 다른 운영 규칙을 확인하면 해당 명시적 규칙을 사용한다. 기타시설 text 타입 변경도 별도의 중앙 정의/데이터 검토 대상이며 이번 코드에서 강제 변환하지 않는다.

추가 검증: stable repository 검사 16개가 통과하여 정식 1.4.3·1.4.4·1.4.5의 기존 SHA256과 후보 1.4.6의 manifest/inventory 일치를 확인했다. 중앙 정의/방향각 검사 18개 통과, PostgreSQL이 필요한 16개는 로컬에서 건너뛰었다. 최초 실행의 Windows 기본 cp949 파일 읽기 오류 5개는 UTF-8 실행으로 재검사하여 통과했다. 별도 프로필의 최초 로딩 및 재시작/재열기 두 단계 모두 UI 시나리오가 통과했다.
