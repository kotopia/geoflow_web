# Django Admin Central Account Policy Decision

## 1. 조사 범위

이 문서는 Django `/admin/` 경로의 현재 인증 경계와 Issue 3B 중앙 계정 활성 상태 guard의 관계를 정적으로 검토한다. 검토 대상은 URL 연결, middleware 순서와 예외 경로, Django 기본 admin 인증 조건, 중앙 `users` 원장 원칙, 운영 복구 및 lockout 위험이다.

코드, 데이터베이스, migration, endpoint 및 운영 설정은 변경하거나 실행하지 않았다. 저장소만으로 확인할 수 없는 실제 `/admin/` 사용 빈도와 외부 접근 통제 상태는 미확인 운영 항목으로 남긴다.

## 2. 현재 Django admin 인증 구조

- `geoflow_project/urls.py`는 `/admin/`을 `admin.site.urls`에 연결한다.
- 별도 custom authentication backend는 정적 검색에서 확인되지 않았다.
- Django admin 인증 주체는 Django auth user이며 기본적으로 해당 계정의 `is_active`와 `is_staff` 상태를 사용한다.
- 중앙 `users`와 Django auth user는 별도 저장소와 lifecycle을 가질 수 있다.
- 따라서 중앙 `users.is_active=false` 또는 중앙 user row missing 상태가 Django admin 계정을 자동으로 비활성화하지 않는다.
- 저장소에서는 별도 MFA 또는 OTP 구현 근거를 확인하지 못했다. 네트워크 제한과 외부 인증 계층의 적용 여부도 코드만으로 확정할 수 없다.

현재 `/admin/`의 실제 운영 목적은 코드에서 확정할 수 없다. 제품의 일상 중앙 관리는 `/control/`을 공식 경로로 삼고, `/admin/`은 긴급 복구에 한정하는 정책을 명시해야 한다.

## 3. Issue 3B guard와 `/admin/` exemption 관계

`CentralAccountActiveGuardMiddleware`는 `AuthenticationMiddleware` 이후에 실행되지만 `/admin`, `/admin/`, `/admin/` prefix를 public/exempt 경로로 둔다. 그러므로 `/admin/` 요청에서는 중앙 `users` lookup과 중앙 active 판정이 수행되지 않는다.

이 exemption은 현재 의도된 보류 상태다. 중앙 DB 장애나 identity mapping 오류가 있을 때 Django admin까지 동시에 잠기는 것을 막지만, 통제되지 않으면 중앙 account policy를 우회하는 privileged path가 된다.

## 4. Option 1: 중앙 account policy 적용안

이 안은 Django admin identity를 중앙 `users` row와 명시적으로 매핑하고, 중앙 row가 없거나 `is_active`가 정확히 true가 아니면 admin 인증 또는 요청을 fail-closed 처리한다.

장점:

- 중앙 `users`가 로그인 계정 원장이라는 제품 원칙과 일관된다.
- 중앙에서 계정을 비활성화하면 일반 서비스와 admin 권한을 함께 철회할 수 있다.
- orphan Django admin 계정이 중앙 정책을 우회하는 위험을 줄인다.
- 계정 lifecycle과 감사 기준을 한 곳에 모으기 쉽다.

필요 조건과 위험:

- Django auth user와 중앙 user 사이의 안정적이고 unique한 mapping 규칙이 필요하다.
- 중앙 DB 장애, lookup 오류, mapping 불일치 시 모든 운영자가 lockout될 수 있다.
- admin login 시점과 기존 admin session 모두에서 active 상태를 재검증해야 한다.
- 중앙 DB 장애를 복구할 별도의 인증 독립 경로와 검증된 restore runbook이 선행되어야 한다.
- 단순히 Issue 3B exemption만 제거하면 admin login redirect loop나 장애 시 전면 lockout을 만들 수 있으므로 허용되지 않는다.

## 5. Option 2: break-glass 예외 유지안

이 안은 `/admin/`을 중앙 `users` 정책과 분리된 긴급 복구용 Django admin으로 유지한다. `/control/`은 평상시 업무용 중앙 관리 경로이며 `/admin/`은 일반 업무에 사용하지 않는다.

장점:

- 중앙 DB 또는 중앙 identity lifecycle 장애 중에도 복구 경로를 보존한다.
- 잘못된 중앙 계정 비활성화나 mapping 배포로 인한 전면 운영자 lockout을 피할 수 있다.
- Phase 1에서 인증 저장소를 결합하는 고위험 변경을 피한다.

필요 조건과 위험:

- 중앙 account policy를 우회할 수 있으므로 예외 자체가 privileged 보안 경계가 된다.
- 접근 가능한 운영자를 극소수로 제한하고 일상 업무 사용을 금지해야 한다.
- 강한 고유 credential, MFA 또는 동등한 외부 인증, 접근망 제한, 접근 감사가 필요하다.
- credential 보관, 사용 승인, 사용 후 rotation, 정기 검증, 퇴사자 제거 절차가 필요하다.
- 위 통제가 준비되지 않았다면 `/admin/`을 공용 네트워크에 운영 노출해서는 안 된다.

## 6. 두 선택지 비교표

| 기준 | Option 1: 중앙 정책 적용 | Option 2: break-glass 예외 |
|---|---|---|
| 중앙 users 원칙 일관성 | 높음 | 명시적 운영 예외 필요 |
| 중앙 계정 비활성화의 admin 철회 | 자동화 가능 | 별도 Django admin lifecycle 필요 |
| 중앙 DB 장애 시 복구성 | 낮아질 수 있음 | 높음 |
| mapping 오류 시 lockout 위험 | 높음 | 낮음 |
| 정책 우회 위험 | 낮음 | 통제 미흡 시 높음 |
| 구현 복잡도 | 높음 | 코드 변경은 작지만 운영 통제 필요 |
| Phase 1 적합성 | lockout 대책 전에는 낮음 | 조건부로 적합 |
| 장기 운영 부담 | identity 동기화 부담 | break-glass credential 및 감사 부담 |

## 7. Lockout 위험 분석

Option 1의 핵심 위험은 중앙 DB가 admin 복구에 필요한 바로 그 장애 지점이 될 수 있다는 점이다. 중앙 lookup을 fail-closed로 강제하면 DB 장애, schema 불일치, 이메일 mapping 오류, middleware 배포 오류만으로 모든 admin 접근이 막힐 수 있다. 특히 중앙 DB를 고쳐야 하는 상황에서 중앙 DB에 의존하는 인증만 남으면 복구 순환 의존성이 생긴다.

중앙 정책 적용 전에는 다음이 검증되어야 한다.

- 중앙 DB와 독립된 복구 주체 및 접근 방식
- Django auth user와 중앙 user의 충돌 없는 mapping
- admin login과 기존 session에 대한 동일한 차단 정책
- 중앙 lookup 장애 시 동작과 redirect-loop 회귀 테스트
- 운영자가 실제로 수행해 본 lockout 복구 runbook
- 최소 두 명 또는 승인된 이중 통제를 통한 복구 가능성

## 8. 보안 우회 위험 분석

Option 2는 복구성을 제공하지만 `/admin/`이 중앙 inactive 정책을 우회한다. 일반 사용자가 Django auth 계정까지 획득하거나 오래된 staff 계정이 방치되면 중앙 계정 비활성화 후에도 privileged 접근이 가능할 수 있다.

위험 완화를 위해 `/admin/`에는 최소 권한, 계정 수 제한, 고유 credential, MFA 또는 접근 프록시의 강한 인증, IP/VPN 등 접근망 제한, rate limiting, 성공 및 실패 로그인 감사, 관리자 변경 감사, 정기 접근 검토와 credential rotation이 필요하다. secret을 command line, systemd unit, 로그 또는 문서에 넣어서는 안 된다.

## 9. 권장 결정

**Phase 1에서는 Option 2를 선택하여 `/admin/`을 제한된 break-glass 운영 예외로 유지한다.**

- 평상시 중앙 사용자·그룹·역할 업무는 `/control/`에서 처리한다.
- `/admin/`은 중앙 계정 또는 중앙 DB 장애 복구에 필요한 긴급 작업에만 사용한다.
- Issue 3B의 `/admin/` exemption은 현재 유지한다.
- 이 결정은 중앙 `users` 원칙을 폐기하는 것이 아니라, 복구 가용성을 위한 좁고 명시적인 운영 예외다.
- 운영 통제가 확인되지 않은 환경에서는 `/admin/`을 공용 네트워크에 노출하지 않는다.
- 중앙 정책 강제 적용은 mapping과 lockout 대책이 설계·검증된 후 별도 이슈로 재평가한다.

## 10. 권장 운영 규칙

1. `/admin/`은 일상 업무용으로 사용하지 않는다.
2. break-glass Django admin 계정은 극소수의 지정 운영자에게만 부여한다.
3. 개인별 고유 계정을 사용하고 공유 계정은 피한다. 불가피한 공유 credential은 승인된 비밀 저장소와 이중 통제로 관리한다.
4. 강한 credential과 MFA를 적용한다. Django 자체 MFA가 없다면 신뢰 가능한 접근 프록시나 IdP 계층을 사용한다.
5. VPN, bastion, allowlist 또는 동등한 접근망 제한을 적용한다.
6. 성공·실패 로그인, 권한 변경, 데이터 변경을 감사하고 경보 기준을 둔다. 감사 로그에는 secret이나 불필요한 개인정보를 남기지 않는다.
7. 정기적으로 계정, staff/superuser 권한, 최근 사용 여부를 검토한다.
8. 사용 후 credential rotation 및 세션 철회 절차를 둔다.
9. 퇴사·역할 변경 시 break-glass 권한을 중앙 계정 변경과 별도로 즉시 회수한다.
10. 중앙 DB 장애, Django auth 장애, credential 분실 상황별 restore runbook을 작성하고 정기적으로 비파괴 검증한다.
11. `/admin/` 사용에는 사유, 승인자, 작업 범위, 시작·종료 시각을 기록한다.
12. application business workflow와 tenant 업무 처리는 `/admin/`에서 수행하지 않는다.

## 11. 구현이 필요한 경우 후속 이슈

### Issue 3C-3A: Break-glass control readiness audit

- 실제 운영 노출 방식, MFA 또는 외부 인증, 접근망 제한, rate limit, 감사 로그 및 alert 상태를 값 없이 확인한다.
- Django admin 계정 수와 권한 검토 방법을 설계하되 실제 identity 값은 기록하지 않는다.
- credential rotation과 emergency access runbook의 책임자를 정한다.

### Issue 3C-3B: Central-policy admin enforcement design

장기적으로 Option 1을 선택할 경우 다음을 먼저 설계한다.

- Django auth user와 중앙 `users`의 immutable mapping key
- admin login 전 active/missing 검사
- 기존 admin session의 재검증과 철회
- 중앙 lookup 장애의 fail-closed 정책
- redirect loop 방지
- 독립 break-glass fallback 또는 복구 절차
- DB-free 단위 테스트와 통제된 integration test

이 설계와 lockout 대책 승인 전에는 Issue 3B exemption을 제거하지 않는다.

## 12. 지금은 보류할 항목

- `/admin/` middleware exemption 제거
- 중앙 user와 Django auth user 자동 동기화
- Django admin 인증 backend 변경
- MFA 제품 또는 접근 프록시 선정과 구축
- Django admin 계정 생성·삭제·권한 변경
- password token 또는 signup approval schema 변경
- join request 흐름 변경
- 운영 데이터나 admin 등록 모델 변경

## 13. 다음 Issue 3D로 넘길 항목

Issue 3D는 Django admin 정책과 분리하여 tenant authorization freshness를 다뤄야 한다.

- active `user_group_map`의 요청별 또는 적절한 주기의 재검증
- 비활성·삭제된 membership의 tenant 접근 철회
- group 상태 및 tenant selectability 재검증
- session의 tenant alias, group, role, permission cache 무효화
- implicit identity 또는 membership provisioning 제거 여부
- 중앙 account active guard와 membership guard의 명확한 실행 순서
- employee profile을 인증 또는 권한 주체로 사용하지 않는 원칙 유지

결론적으로 Phase 1의 현재 안전한 선택은 `/admin/`을 통제된 break-glass 예외로 유지하고 `/control/`을 공식 중앙 관리 경로로 사용하는 것이다. 중앙 정책을 Django admin에 강제하는 변경은 독립 복구 경로와 lockout 방지 대책이 준비된 이후에만 진행한다.
