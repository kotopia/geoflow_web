# GeoFlow Finance Development History

> 목적: Finance 구축 과정에서의 의사결정, 구현 순서, 실패 원인과 해결책을 재현 가능하게 기록한다.
>
> 기준일: 2026-09-03

## 1. 문서 범위

이 문서는 단순 변경 로그가 아니다.

PR별 구현 내용뿐 아니라 다음을 함께 기록한다.

- 왜 구조를 바꿨는지
- 어떤 방식이 실제 운영에서 실패했는지
- 실패 원인이 코드, 데이터, migration, UI, 배포 중 어디에 있었는지
- 다음 개발자가 같은 문제를 반복하지 않기 위한 기준

Finance의 최종 구조 원칙은 [`finance-architecture.md`](./finance-architecture.md)를 기준으로 한다.

---

## 2. 초기 설계 결론

Finance를 별도 메뉴로 만들되 계약/프로젝트/거래처와 연결하는 방향으로 시작했다.

초기 핵심 결론:

- 기존 Excel 세금계산서/입출금대장을 Web 기반으로 옮긴다.
- 계약을 Finance의 기본 연결축으로 사용한다.
- 프로젝트는 필수가 아니라 선택 연결로 둔다.
- 거래처는 기존 partner 데이터를 참조한다.
- 향후 청구/지급/미수금/손익까지 확장할 수 있도록 구조를 열어둔다.
- 설정값은 가능한 한 `ops.settings_nodes`를 활용한다.

---

## 3. Phase 1 및 Excel/증빙 기반 구축

### PR #268 — Complete Finance Phase 1 with XLSX import and evidence files

주요 구현:

- 세금계산서 XLSX import
- 입출금대장 XLSX import
- header 기반 컬럼 매핑
- 계약/프로젝트/거래처/계좌 매칭
- 세금계산서 승인번호 중복 검사
- 증빙 관리 화면
- private S3 업로드/다운로드
- short-lived presigned URL
- Finance 메뉴 확장

당시 `openpyxl`을 XLSX reader로 사용했다.

이 단계에서 Finance가 단순 입력폼이 아니라 **외부 회계자료를 받아들이는 업무 시스템**으로 방향이 확정됐다.

---

## 4. CRUD, 팝업 입력, 삭제와 import preview

### PR #270 — Finance v2: modal editing, safe deletion, and preview imports

실무 테스트 후 목록 우선 UX로 변경했다.

주요 변경:

- list-first 화면
- Bootstrap modal 신규/수정
- 계약/거래처 searchable selector
- 공급가액/부가세/합계 자동 계산
- 청구, 세금계산서, 지급, 입출금 수정
- soft delete
- 삭제함 복원
- tenant_admin 영구삭제
- HomeTax import preview
- header 자동 인식 및 header 행 변경
- 중복 비교 후 선택 저장

### 당시 중요 결론

삭제는 즉시 DB row를 제거하는 기능이 아니라 다음 흐름으로 만들었다.

```text
일반 사용자 삭제
-> soft delete
-> 삭제함
-> 복원 또는 tenant_admin 영구삭제
```

이 원칙은 이후 계좌/카드까지 확대됐다.

---

## 5. Modal selector 문제와 금액 표시

### PR #271 — Fix Finance modal selectors and display formatting

### 문제

Choices 계열 selector를 숨겨진 Bootstrap modal 상태에서 초기화하면 layout/option 상태가 불안정해졌다.

### 해결

- modal lifecycle에 맞춰 selector 초기화/해제
- create/edit reset 때 native option 보존
- 금액 입력 천단위 표시
- backend는 comma 포함 금액 파싱 허용
- 코드값을 설정 display name으로 표시

### 교훈

**숨겨진 modal에서 UI component를 선행 초기화하지 않는다.**

DOM이 보이는 시점과 library lifecycle을 맞춰야 한다.

---

## 6. 은행 Excel import 실패와 Calamine 전환

### PR #272 — Finance import: support bank XLS/XLSX formats

실제 IBK/농협 파일을 테스트하면서 기존 XLSX import 방식의 한계가 드러났다.

### 실패 원인

IBK workbook 중 일부가 비표준/특수 style metadata를 포함했고, `openpyxl`이 CellStyle을 생성하는 과정에서 오류가 발생했다.

즉, **셀 값 자체가 잘못된 것이 아니라 workbook style metadata 때문에 import 전체가 실패**했다.

### 해결

active bank import reader를 `python-calamine`으로 교체했다.

추가 구현:

- `.xlsx` + legacy `.xls`
- 상위 30행 header 탐색
- IBK `거래일시`, `출금`, `입금`, `상대계좌예금주명`, `상대은행`
- 농협 `출금금액(원)`, `입금금액(원)`, `거래기록사항`, `이체메모`
- 출금/입금 split column에서 direction 자동 계산
- 거래일이 없는 합계 row 제외

### 재발 방지

Excel import에서는 workbook styling보다 **raw cell data를 안정적으로 읽는 것**을 우선한다.

---

## 7. 귀속회사와 Finance 페이지 분리

### PR #273 — Finance: split subpages and add own-organization ownership

Finance가 커지면서 하나의 화면보다 업무별 subpage로 분리했다.

분리된 영역:

- 대시보드
- 청구
- 세금계산서
- 지급
- 입출금대장
- 잔액/관련 조회
- 계좌/카드

### 핵심 구조 변경

`my_org_unit_id`를 Finance 공통 ownership axis로 추가했다.

대상:

- accounts
- claims
- payment requests
- tax invoices
- transactions
- cards

계약 선택 시 내부 귀속회사를 기본으로 연결하는 방향을 도입했다.

### 교훈

회사 단위 집계가 필요한 시스템에서 귀속회사를 화면 필터만으로 처리하면 안 된다.

**row 자체가 어느 회사에 속하는지 저장해야 한다.**

---

## 8. 계좌/카드 수정·삭제, iframe 문제, 계약 기본값

### PR #274 — Fix Finance follow-up UX and routing issues

### 문제 1: 계좌/카드 관리가 불완전

계좌/카드도 수정과 삭제가 필요했다.

해결:

- account/card edit
- soft deactivate/delete
- 공통 삭제함 연계 기반 마련

### 문제 2: Excel import iframe refusal

localhost 테스트에서 import popup이 iframe 보안정책 때문에 거부되는 문제가 발생했다.

해결:

- SAMEORIGIN frame-safe security wrapper를 통해 import route 제공

### 문제 3: 계약 선택 후 기본값 중복 입력

사용자가 계약을 선택했는데도 귀속회사/발주처를 다시 입력해야 했다.

해결:

- contract-defaults endpoint 추가
- 계약 선택 시 귀속회사 자동 선택
- 계약 발주처를 거래처 기본값으로 사용
- 사용자는 이후 거래처 override 가능
- backend save-time fallback 추가

### 교훈

자동 채움은 UI 편의만으로 끝내지 않고 **backend에서도 동일 default 규칙을 적용**해야 한다.

---

## 9. Import 행별 매핑, 회사 필터, 통합 삭제함

### PR #275 — Finance: row mapping, company filter, unified trash, avatar preload

Finance 1차 구축의 주요 실무 요구를 반영한 단계다.

### Excel import

기존 setup-level default contract/default partner 방식은 제거했다.

최종 방향:

- source page가 import 유형 고정
- popup에서 유형 선택 제거
- preview 각 행에 계약/거래처 매핑
- 체크된 행에 일괄 적용
- 계약 선택 시 계약 client 자동 선택
- 거래처 override 허용

### 귀속회사 필터

- `귀속회사` selector 추가
- all company / specific company
- session persistence
- 목록과 dashboard aggregate에 동일 적용

### 통합 삭제함

다음 유형을 하나의 Finance trash에서 처리하도록 확장했다.

- claim
- invoice
- payment
- transaction
- account
- card

계좌/카드에는 다음 필드를 추가하는 migration `0034_finance_account_card_trash`를 도입했다.

- `is_deleted`
- `deleted_at`
- `deleted_by`

계좌 hard purge는 transaction FK 참조가 있으면 차단한다.

---

## 10. Local 삭제함 500 오류: migration drift

### 증상

Finance 삭제함 접속 시 다음 오류가 발생했다.

```text
psycopg2.errors.UndefinedColumn: column "deleted_at" does not exist
```

오류 위치는 `fin.accounts`/`fin.cards`를 포함한 통합 trash query였다.

### 원인

코드는 이미 PR #275 기준으로 `deleted_at` 컬럼을 사용하고 있었지만 local `cheonan_db`에는 `0034_finance_account_card_trash`가 적용되지 않았다.

즉, 애플리케이션 로직 문제가 아니라 **코드와 tenant DB migration 상태의 불일치(schema drift)**였다.

### 해결

0034를 적용해 다음 필드를 추가했다.

```text
fin.accounts.is_deleted
fin.accounts.deleted_at
fin.accounts.deleted_by
fin.cards.is_deleted
fin.cards.deleted_at
fin.cards.deleted_by
```

이후 직원 이력용 0035까지 포함해 local schema를 release와 맞췄다.

### 재발 방지

새 코드를 pull한 뒤 화면 오류가 컬럼/테이블 없음 형태라면 먼저 migration 적용 상태를 확인한다.

코드에서 예외를 숨겨 schema drift를 임시 회피하지 않는다.

---

## 11. 0035와 같은 release에서의 schema catch-up

### PR #276 — Employee history: education settings and career certificate number

0035는 Finance 기능 자체가 아니라 직원 이력 기능 변경이었다.

다만 production release 시 tenant DB의 migration 상태를 한 번에 현재 release까지 맞출 필요가 있었기 때문에 Finance 0030~0034와 함께 0035까지 catch-up 대상으로 포함했다.

이 단계에서 local 테스트와 production migration의 기준을 `release/stabilized-deploy` dependency chain으로 맞추는 원칙이 강화됐다.

---

## 12. Production deployment 1차 실패

### PR #278 — Ops: guarded production release deployment

Finance 변경이 누적된 뒤 운영 tenant migration과 코드 배포를 안전하게 수행하기 위해 GitHub Actions 기반 guarded deployment를 만들었다.

배포 전/후 검증:

- exact release SHA 확인
- production working tree clean 확인
- service pre-health check
- requirements install
- `pip check`
- `manage.py check`
- tenant migration dry-run
- schema validation
- `collectstatic`
- systemd restart
- local Gunicorn health check
- public HTTPS `/login/` 200 확인
- 실패 시 application code rollback

### 실제 실패

1차 deployment run에서 다음 오류가 발생했다.

```text
RuntimeError: geoflow_control: dependency 0029 not applied
```

그 전에 실제 tenant였던 다음 DB는 dry-run을 정상 통과했다.

```text
geoflow_iroom251231
geoflow_dlit20251231
```

### 원인

배포 스크립트가 중앙 Control DB인 `geoflow_control`을 active group DB라는 이유만으로 tenant DB로 취급했다.

하지만 `geoflow_control`은 tenant schema가 아니므로 tenant migration `0029_unified_settings_registry`가 없는 것이 정상이다.

### 안전장치가 작동한 결과

- migration은 dry-run 단계에서 실패했기 때문에 tenant DB에 부분 commit되지 않았다.
- application code는 이전 SHA로 rollback됐다.
- 운영 서비스는 기존 상태로 복구됐다.

### 핵심 교훈

**tenant 여부를 group status, DB 이름, config 존재 여부만으로 판단하면 안 된다.**

---

## 13. Production deployment v2 성공

### PR #279 — Fix production deploy tenant classification

1차 실패의 원인을 반영해 tenant DB 판별 기준을 변경했다.

Tenant schema marker:

```text
ctr.contracts
prj.projects
hr.employee_profile
ops.settings_nodes
```

판별 규칙:

- marker가 하나도 없음 → non-tenant로 skip
- marker 일부만 존재 → partial schema로 보고 deployment 실패
- marker 모두 존재 → real tenant로 migration 수행

### 성공 결과

`geoflow_control`은 정상적으로 제외됐다.

```text
production_deploy_v2_skipped_non_tenant=geoflow_control
```

실제 tenant 3개는 모두 dry-run 및 migration에 성공했다.

```text
production_deploy_v2_tenant_dry_run_ok=geoflow_iroom251231
production_deploy_v2_tenant_dry_run_ok=geoflow_dlit20251231
production_deploy_v2_tenant_dry_run_ok=cheonan_db

production_deploy_v2_tenant_migrated=geoflow_iroom251231
production_deploy_v2_tenant_migrated=geoflow_dlit20251231
production_deploy_v2_tenant_migrated=cheonan_db
```

적용 범위:

```text
0030 -> 0031 -> 0032 -> 0033 -> 0034 -> 0035
```

운영 release:

```text
f4840310bcea1d8ad2e9a28ab7f27cc063c516a0
```

최종 health check:

```text
production_deploy_v2_public_login_status=200
production_deploy_v2_complete=yes
```

이후 release branch에는 다른 기능 변경이 추가될 수 있으므로 위 SHA는 **Finance 누적 변경을 production에 성공적으로 배포한 시점의 기준 SHA**로 기록한다.

---

## 14. collectstatic 중복 static path 경고

성공한 production deploy에서 `collectstatic`은 완료됐지만 다음 유형의 경고가 다수 존재했다.

```text
Found another file with the destination path ...
It will be ignored since only the first encountered file is collected.
```

대상에는 `control/css`, fonts, avatars, flags, JS 등이 포함됐다.

현재 deployment 실패 원인은 아니었고 public health check도 200이었다.

다만 앞으로 정리해야 할 기술부채다.

### 후속 원칙

- static destination path는 가능한 한 유일해야 한다.
- 동일 파일명이 여러 static source에 존재하면 실제 production에서 어떤 파일이 선택되는지 모호해질 수 있다.
- Finance와 직접 관련된 장애는 아니지만 release 안정성 차원에서 별도 정리 대상이다.

---

## 15. 2026-09-03 계약/프로젝트 타임라인 논의

Finance 1차 기능을 구축한 뒤 청구와 계약 이벤트의 중복 입력 문제가 다시 검토됐다.

### 처음 고려한 방식

계약 타임라인에서 `청구`를 클릭하면 Finance 청구 화면으로 이동하고, 저장 후 계약 이벤트에 `청구 완료`를 자동 생성하는 방식.

### 문제

이 방식도 결과적으로 같은 사실을 Finance와 event table에 두 번 저장한다.

동기화 책임이 생긴다.

### 최종 결론

- 청구/세금계산서/입금 등 Finance 성격의 데이터는 Finance에만 저장
- 계약 이벤트에서 재무 입력 항목 제거
- 계약 타임라인 표시 시 Finance 데이터를 직접 조회
- 계약 주요 이벤트 + Finance 주요 활동을 기본 타임라인으로 표시
- 프로젝트의 현장작업/성과심사 등 상세 이벤트는 프로젝트 범위에서 관리
- 계약 화면의 `모두 보기` 옵션에서 프로젝트 이벤트까지 합쳐 표시

즉, 타임라인은 단일 event table viewer가 아니라 **여러 source를 조합하는 activity timeline**으로 확장한다.

이 설계는 결정됐지만 2026-09-03 문서 작성 시점에는 아직 구현되지 않았다.

---

## 16. 주요 실패와 재발 방지 요약

| 실패/문제 | 원인 | 해결 | 재발 방지 원칙 |
|---|---|---|---|
| Hidden modal selector 불안정 | 숨겨진 상태에서 UI library 초기화 | modal lifecycle에 맞춰 초기화 | visible lifecycle과 component lifecycle 일치 |
| IBK Excel 읽기 실패 | openpyxl이 style metadata 처리 중 실패 | Calamine 전환 | import는 raw data 안정성을 우선 |
| Excel iframe refusal | frame security 정책 | SAMEORIGIN wrapper | embedded route는 frame policy 명시 |
| `deleted_at` 없음 | 코드보다 DB migration이 뒤처짐 | 0034 적용 | schema drift 먼저 점검 |
| Production deploy 실패 | `geoflow_control`을 tenant로 오인 | schema marker 기반 판별 | tenant는 schema로 검증 |
| 청구 이중 입력 우려 | event와 Finance에 같은 사실 저장 | Finance Source of Truth | 동일 업무 사실을 복제하지 않음 |

---

## 17. 주요 PR 인덱스

- #268 — Finance Phase 1 XLSX import + evidence
- #270 — modal CRUD + soft delete + preview import
- #271 — modal selector + 금액/표시명 수정
- #272 — 은행 XLS/XLSX + Calamine
- #273 — 귀속회사 + Finance subpage 분리
- #274 — account/card edit/delete + iframe + contract defaults
- #275 — 행별 import 매핑 + 회사 필터 + 통합 삭제함
- #276 — 0035 employee schema catch-up 관련 release 후속
- #278 — guarded production deploy v1
- #279 — tenant 판별 수정 + production deploy v2 성공

---

## 18. 현재 남은 후속 과제

### 결정됨 / 미구현

- 계약 타임라인에서 Finance 레코드 통합 조회
- 계약 기본 타임라인과 프로젝트 상세 이벤트 분리
- `모두 보기` 옵션
- Finance timeline item 클릭 시 원본 Finance 화면으로 이동

### 기술부채

- duplicate static destination path 정리
- Finance 전용 permission namespace 분리 검토
- 프로젝트별 원가/손익이 필요해질 경우 project linkage 활용 확대

---

## 19. 문서 업데이트 규칙

Finance의 중요한 변경은 PR 설명만 남기지 말고 이 문서에도 다음 형식으로 누적한다.

```text
날짜
- 변경 배경
- 결정
- 구현
- 실패/예외
- 운영 반영 결과
- 재발 방지 또는 후속 과제
```

이 기록의 목적은 '무엇을 만들었는가'보다 **왜 현재 구조가 이렇게 되었는가를 Git만으로 복원 가능하게 만드는 것**이다.
