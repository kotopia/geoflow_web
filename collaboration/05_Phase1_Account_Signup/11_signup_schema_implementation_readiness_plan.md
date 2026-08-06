# Signup Schema Implementation Readiness Plan

## 1. 조사 범위

이 문서는 GeoFlow Phase 1의 signup/account approval schema 구현 전에 필요한 central DB 구조, migration 순서, service 경계, 테스트 범위, rollout 및 rollback 위험을 정리한다. 다음 문서를 기준으로 작성했다.

- `docs/planning/GeoFlow_Product_Structure_v1.md`
- `collaboration/05_Phase1_Account_Signup/02_central_signup_schema_verification.md`
- `collaboration/05_Phase1_Account_Signup/03_signup_invitation_schema_design.md`
- `collaboration/05_Phase1_Account_Signup/09_join_request_account_provisioning_policy_audit.md`
- `collaboration/05_Phase1_Account_Signup/10_privileged_missing_user_provisioning_policy_decision.md`

이번 이슈는 implementation readiness를 확정하는 planning 작업이다. 코드, model, migration, DB, endpoint, browser 및 기존 join approval 흐름은 변경하지 않았다. 실제 DB row, 이메일, UUID, session, password, token, invitation 원문, secret 및 환경설정 값도 조회하거나 출력하지 않았다.

## 2. 현재까지 확정된 account/membership 정책

1. 중앙 `users`는 로그인 가능한 계정의 유일한 원장이다.
2. `users.is_active=true`는 login 가능 여부의 최종 gate이며, password 검증 성공만으로 session을 발급해서는 안 된다.
3. signup/account approval과 group/role membership approval은 별도 lifecycle과 별도 승인 행위다.
4. `join_requests`는 group/role membership 요청 원장이며 signup approval 원장으로 재사용하지 않는다.
5. Phase 1의 일반 join approval은 existing active central user만 처리한다. Missing/inactive user provisioning과 privileged one-step onboarding은 제공하지 않는다.
6. Password setup은 credential 설정 절차일 뿐 account approval이나 activation이 아니다.
7. `email_verified=true`는 이메일 통제 확인일 뿐이며 단독으로 login을 허용하지 않는다.
8. Invitation code는 optional provenance 및 suggestion 수단이다. Account 또는 membership을 auto-approve하지 않는다.
9. Tenant `employee_profile`은 인증 또는 권한 주체가 아니며 signup/account approval에서 자동 생성하지 않는다.
10. Signup 관련 schema와 transaction은 central DB에만 위치한다.
11. Account approval은 central account만 활성화한다. `join_requests`나 `user_group_map`을 자동 생성·활성화하지 않는다.
12. Membership activation은 active account에 대해서만 별도 권한과 transaction으로 수행한다.

## 3. 구현 대상 schema 목록

Phase 1 구현 후보는 다음 네 구조다.

| 구조 | Phase 1 판단 | 책임 |
|---|---|---|
| `signup_requests` | 필수 | 신청의 현재 상태와 최소 심사 자료 원장 |
| `signup_request_events` | 필수 | 신청 생성 및 상태 전이의 append-only 이력 |
| `invitation_codes` | invitation 기능을 같은 rollout에 포함할 때 필수 | invitation 발급·만료·폐기·사용 한도 정책 |
| `signup_invitation_events` 또는 동등한 `invitation_code_uses` | invitation 기능을 포함할 때 필수 | code 검증·연결 provenance와 사용량 근거 |

Suggested group/role은 v1에서 `invitation_codes.suggested_group_id`와 `suggested_role_id`로 표현하는 안을 우선 검토한다. 하나의 신청에 여러 suggestion, invitation과 무관한 suggestion, suggestion별 검토 상태가 필요하다는 제품 요구가 확정될 때만 별도 `signup_request_membership_suggestions` 구조로 분리한다. 이 구조는 어디까지나 비권위적 제안이며 `join_requests` 또는 `user_group_map`을 대신하지 않는다.

## 4. 각 table의 목적과 책임

### 4.1 `signup_requests`

Account signup 신청의 authoritative current state를 저장한다. 최소 후보 필드는 `id`, `user_id`, `status`, 제한된 연락·조직·가입 목적, 약관/개인정보 처리방침 version과 server-side 동의 시각, 제출/결정 시각, 결정 actor, 통제된 reason code, 길이가 제한된 sanitized note, optimistic concurrency용 `version`, 생성/수정 시각이다.

핵심 제약은 다음과 같다.

- `user_id`는 central `users.id`를 참조하고 삭제는 restrictive하게 처리한다.
- 한 user에는 open 상태(`pending_email_verification`, `pending_approval`) 신청이 최대 하나만 존재한다.
- `password_hash`, invitation 원문, token, session, raw request body를 저장하지 않는다.
- 승인/거절에 필요한 결정 필드는 상태와 일관되어야 한다.
- `status`와 current-state 필드는 조회 편의를 위한 현재 원장이고, 전이 역사는 event table이 보존한다.
- 재신청은 terminal row를 되돌리지 않고 같은 inactive user에 새 request를 만든다.

### 4.2 `signup_request_events`

신청 제출, 이메일 검증, 승인, 거절, 철회 및 만료를 append-only로 기록한다. 최소 후보 필드는 request FK, event type, 이전/이후 상태, actor central user ID, 통제된 reason code, 제한된 sanitized note, 생성 시각이다.

Event는 정상 운영에서 update/delete하지 않는다. Request lock 또는 조건부 version update, event append, current status update 및 필요한 account activation을 한 central transaction으로 묶는다. 기존 범용 `audit_events`는 보조 security/administrative log로 사용할 수 있지만 signup 상태 복원의 원장이 아니다.

### 4.3 `invitation_codes`

Optional invitation의 lifecycle과 policy를 저장한다. 최소 후보 필드는 code의 keyed digest, digest key ID, 상태, issuer, 선택적 suggested group/role, 만료 시각, 최대/현재 사용 횟수, revoke actor/reason/time, 생성/수정 시각이다.

Invitation은 provenance와 reviewer용 suggestion만 제공한다. 유효한 code도 `signup_requests`를 승인하거나 `users.is_active`, `join_requests`, `user_group_map`을 변경하지 않는다.

### 4.4 `signup_invitation_events` 또는 `invitation_code_uses`

Invitation과 signup request의 성공적인 검증·연결을 추적하는 immutable 구조다. 명칭보다 중요한 계약은 request FK와 invitation FK, event/use type, 선택적 actor, 생성 시각을 보존하고 한 request에 성공적으로 연결된 invitation을 최대 하나로 제한하는 것이다.

`use_count` 증가와 request 연결은 invitation row lock 또는 동등한 atomic condition 아래 같은 transaction에서 처리한다. Invalid code 시도에는 공격자가 보낸 원문이나 파생 digest를 저장하지 않고, 필요하면 rate-limited aggregate security telemetry만 남긴다. 사용량 복구(`released`)는 취소 시 code 사용 횟수를 돌려준다는 정책이 별도 확정되지 않으면 v1에서 구현하지 않는다.

## 5. `users` table과 `signup_requests`의 관계

Phase 1 권장안은 signup 제출 시 central `users`를 명시적으로 `is_active=false`, `email_verified=false`로 만들고 같은 transaction에서 `signup_requests`와 최초 event를 생성하는 방식이다. DB default에 활성 상태를 맡기지 않는다.

이 방식을 선택하는 이유는 현재 signup UX가 password를 수집하며, password hash를 기존 account 원장인 `users`에만 저장할 수 있기 때문이다. `signup_requests`에 password hash를 복제하거나 임시 credential을 보관하지 않는다. 향후 approval-before-password UX로 변경하면 user를 approval 시점에 만들고 승인 후 one-time password setup을 수행하는 대안을 별도 재검토한다.

필수 관계와 전이 계약은 다음과 같다.

- User와 request 생성은 하나의 central transaction이다. 어느 한쪽 생성이 실패하면 둘 다 남지 않는다.
- Password는 제출 service에서 Django password validation 후 hash로 만들어 `users.password_hash`에만 저장한다. 원문은 persistence, log, event에 전달하지 않는다.
- 이메일 검증 완료는 `users.email_verified=true`와 request의 `pending_approval` 전이를 원자적으로 기록하되 `is_active`는 false로 유지한다.
- Account approval은 expected `pending_approval` request를 `approved`로 바꾸고 `users.is_active=true`로 바꾸며 승인 event를 같은 transaction에서 기록한다.
- Approval의 기본 precondition은 `email_verified=true`다. 이 precondition을 완화하려면 별도 제품·보안 결정을 문서화해야 한다.
- Rejected/withdrawn/expired request와 연결된 신규 account는 inactive로 유지한다. 해당 상태가 user 삭제를 자동 유발하지 않는다.
- 이미 approved된 account를 나중에 suspend하는 것은 account administration이며 historical signup status를 변경하지 않는다.
- Existing active user의 동일 이메일 signup은 새 account/request를 만들지 않고 sanitized conflict로 종료한다.
- Existing inactive user는 open request가 있으면 중복 생성하지 않는다. Terminal request만 있으면 보존·재신청 정책에 따라 같은 user에 새 request를 허용하되 identity와 이메일 변경 규칙을 검증한다.
- Email 정규화와 uniqueness는 현재 central `users`의 case-insensitive unique 계약과 동일한 canonical helper를 사용해야 한다. Race는 application 사전 확인이 아니라 DB uniqueness와 transaction 오류 매핑으로 최종 차단한다.
- Pending 상태에서 account 이메일 변경은 v1에서 금지하는 안을 기본으로 한다. 변경이 필요하면 기존 검증 폐기, 재검증 및 immutable event 정책을 별도 설계한다.

## 6. `invitation_codes`의 역할과 보안 원칙

- Code는 cryptographically secure random source로 충분한 entropy를 갖게 생성한다.
- 문서화된 versioned normalization 후 keyed HMAC digest(예: HMAC-SHA-256)만 저장한다. 평문이나 복호화 가능한 값을 DB에 저장하지 않는다.
- HMAC key는 DB, log 및 event 밖에서 관리하고 DB에는 비밀이 아닌 `digest_key_id`만 둔다.
- 검증은 active 상태, 미만료, `use_count < max_uses`, digest 일치를 모두 요구한다.
- 존재 여부를 구분할 수 없는 동일한 public 오류를 사용하고 rate limit을 적용한다.
- Code를 URL, log, analytics, event, 관리자 note 또는 오류 메시지에 넣지 않는다.
- Key rotation은 여러 key ID를 제한된 기간 지원하며 active code를 조용히 무효화하지 않는다.
- Revocation은 v1에서 irreversible로 하고 필요하면 새 code를 발급한다.
- Suggested group/role은 표시·검토용이며 실제 membership write로 자동 연결하지 않는다.

## 7. `signup_request_events`의 역할

Event table은 "누가, 어떤 근거로, 언제, 어떤 상태를 어떤 상태로 바꿨는가"를 복원하는 workflow history다. Initial/system event는 null actor와 통제된 event type을 사용할 수 있고, approve/reject는 권한이 확인된 central actor가 필수다.

Event note에는 email, UUID의 불필요한 복제, credential, token, invitation 원문, session, raw payload 또는 민감한 runtime context를 넣지 않는다. 운영 검색이 필요한 값은 bounded reason code와 parent FK로 표현한다. Notification 성공/실패는 account approval 상태와 분리하며, 필요하면 별도 delivery 상태/queue에서 재시도한다.

## 8. 상태 모델과 허용 전이

| 현재 상태 | 조건/행위 | 다음 상태 | `users` 영향 |
|---|---|---|---|
| 없음 | 유효한 signup 제출 | `pending_email_verification` | inactive user 생성 |
| `pending_email_verification` | email 검증 완료 | `pending_approval` | `email_verified=true`, inactive 유지 |
| `pending_email_verification` | 검증 기한 만료 | `expired` | inactive 유지 |
| `pending_email_verification` | 신청자 철회 | `withdrawn` | inactive 유지 |
| `pending_approval` | 권한 있는 승인 | `approved` | 같은 transaction에서 active 전이 |
| `pending_approval` | 권한 있는 거절 | `rejected` | inactive 유지 |
| `pending_approval` | 신청자 철회 | `withdrawn` | inactive 유지 |
| `pending_approval` | 심사 기한 만료 | `expired` | inactive 유지 |
| `rejected`/`withdrawn`/`expired` | 허용된 재신청 | 새 request의 초기 상태 | 기존 inactive user 재사용 |

`approved`, `rejected`, `withdrawn`, `expired`는 해당 request의 terminal 상태다. Terminal request를 pending으로 되돌리거나 decision event를 수정하지 않는다. 승인된 request의 취소나 account suspension은 signup 상태 rewind가 아니라 별도 account administration이다.

초기 release가 이메일 검증을 아직 제공하지 않는 경우 request를 `pending_approval`에서 시작할 수는 있으나, 이는 schema 삭제가 아니라 feature sequencing이다. 이 경우에도 approval precondition과 unverified-email 위험을 명시적으로 결정해야 하며 `email_verified=true`를 임의로 기록해서는 안 된다.

## 9. Migration 순서 제안

이 순서는 후속 Issue 4B의 migration draft를 위한 제안이며 이번 문서는 migration 실행을 승인하지 않는다.

1. Central unmanaged table의 ownership과 새 table의 Django managed 여부, migration router가 central-only임을 확정한다.
2. Table/constraint/index 이름 충돌 및 DB 지원 기능을 metadata 수준에서 사전 점검한다. 실제 row는 조회하지 않는다.
3. 첫 migration은 신규 table, FK, check, index만 추가한다. 기존 `users`, `join_requests`, `user_group_map`의 column/default/의미는 변경하지 않는다.
4. Core signup migration에 `signup_requests`와 `signup_request_events`를 먼저 포함한다.
5. Invitation을 별도 release로 분리할 수 있으면 `invitation_codes`와 invitation use/event 구조를 독립 additive migration으로 둔다. 같은 release라면 core 뒤 dependency를 명시한다.
6. Read-capable model/repository를 feature disabled 상태로 배포하고 central routing 및 tenant DB 비생성을 검증한다.
7. Inactive login 및 기존 session guard regression이 통과한 뒤 inactive user + request transactional write를 제한적으로 enable한다.
8. Authorization, concurrency, idempotency 테스트가 통과한 뒤 approval/rejection service를 enable한다.
9. Invitation validation은 account approval과 분리된 feature flag로 enable한다.
10. 기존 active user는 legacy-approved account로 취급하며 가짜 signup request/event를 backfill하지 않는다. 알 수 없는 invitation provenance도 backfill하지 않는다.

Migration 전에 확정할 gate는 exact column type/length, FK `on_delete`, partial unique index 지원 방식, check constraint 범위, UUID 생성 방식, timestamp/default ownership, event table 명칭, retention 정책 및 invitation을 core와 함께 배포할지 여부다.

## 10. Service layer 분리안

| Service | 책임 | 명시적 비책임 |
|---|---|---|
| Public signup form/service | 입력 validation, email normalization, password validation, generic 오류, rate limit 경계 | DB orchestration, activation, membership |
| Signup request creation service | inactive user·request·initial event 원자 생성, optional invitation handoff | approval, membership write, notification을 transaction 안에서 전송 |
| Email verification service | one-time token 검증, replay/expiry 차단, `email_verified` 및 request 전이 | `is_active=true`, account approval |
| Admin decision service | 권한, expected state/version, actor/reason 검증, approve/reject orchestration | membership 승인, invitation 발급 |
| Account activation service | 승인 transaction 안에서만 `is_active=true` 전이 및 불변조건 확인 | 독립 public activation endpoint, password setup |
| Invitation validation service | normalization, digest lookup, validity/usage atomic check, provenance link | auto approval, `user_group_map` write |
| Password setup service | one-time credential 설정과 token lifecycle | signup 승인, account activation, membership |
| Join request membership service | existing active account의 group/role 승인 | user 생성, inactive activation, signup 상태 변경 |

Public/controller layer는 이 service들을 우회해 repository write를 직접 조합하지 않는다. Central DB alias는 request payload나 URL에서 선택하지 않고 server-owned routing으로 고정한다. Transaction 후 email은 commit 이후 queue/outbox 성격의 후속 처리로 보내며 delivery 실패가 승인 transaction을 되돌리거나 중복 활성화를 만들지 않게 한다.

## 11. Password setup과의 관계

- Signup 제출 시 password를 받는 Phase 1 권장안에서는 validation과 hashing 후 `users`에만 저장한다.
- Password hash 존재 또는 setup 완료는 account 승인 증거가 아니다.
- Password setup service는 `users.is_active`와 `signup_requests.status`를 변경하지 않는다.
- Email verification을 password setup에 함께 수행하는 기존/향후 경로가 있어도 `email_verified=true`만 기록하며 activation하지 않는다.
- Pending/rejected/withdrawn/expired account에 password가 있어도 login은 `is_active=false`로 차단한다.
- Setup token은 원문 저장·로그를 금지하고 expiry, single-use, replay 방지 및 대상 binding을 별도 테스트한다.
- 승인 전후 token 발급 시점과 승인 후 password 미설정 account의 UX는 Issue 4F에서 확정한다.

## 12. Join request와의 관계

`signup_requests`는 account 신청 원장이고 `join_requests`는 membership 요청 원장이다. 두 상태를 합치거나 한쪽 승인으로 다른 쪽을 암묵적으로 승인하지 않는다.

- 일반 join approval은 existing active account에만 허용한다.
- Missing/inactive user면 join request를 승인하거나 user, active membership, setup token을 생성하지 않는다.
- Signup approval은 `user_group_map`을 생성하거나 활성화하지 않는다.
- Invitation의 group/role suggestion은 non-authoritative metadata다.
- Account가 active가 된 후 별도 membership workflow와 별도 permission으로 suggestion을 검토한다.
- `central_repo.create_user`, 기존 join endpoint, `user_group_map` write logic 및 Django admin 정책을 signup 구현에 재사용하거나 수정하는 일은 각 후속 이슈에서 명시적 승인 없이는 하지 않는다.

## 13. 테스트 계획

### 13.1 Schema 및 migration 테스트

- 새 구조가 central DB에만 생성되고 tenant migration 대상이 아님을 검증한다.
- 기존 `users`, `join_requests`, `user_group_map`의 schema/default/semantic 변경이 없음을 검증한다.
- Allowed status, positive version/use limits, one-open-request, invitation digest uniqueness 및 event FK/index 제약을 검증한다.
- Fresh install과 현행 central schema에서의 forward migration을 각각 검증한다.
- Application rollback 후 새 table을 보존한 채 feature가 disable되는지 검증한다.

### 13.2 Signup 및 account lifecycle

1. Signup 생성 시 user는 명시적으로 `is_active=false`이고 request와 initial event가 함께 생성된다.
2. Signup 생성만으로 password가 유효해도 login할 수 없다.
3. `email_verified=true`만으로 login할 수 없다.
4. Expected pending request의 authorized approval 후에만 request approval과 `is_active=true`가 원자적으로 완료된다.
5. Rejected/withdrawn/expired request의 user는 login할 수 없다.
6. Duplicate email과 concurrent submission은 user/request 중복 없이 sanitized 오류로 끝난다.
7. Existing active user 재신청은 account/request를 추가 생성하지 않는다.
8. Terminal request 재신청은 새 request/event history를 만들고 과거 row를 수정하지 않는다.
9. Stale version, 중복 승인, 동시 approve/reject는 하나의 terminal 결과만 만든다.
10. Request/event/account 중 하나라도 실패하면 partial state가 남지 않는다.

### 13.3 Invitation

- Code가 없어도 일반 signup이 가능하다.
- 유효 code는 provenance와 suggestion만 기록하고 account를 auto-approve하지 않는다.
- 유효 code도 membership을 생성하거나 활성화하지 않는다.
- Invalid/expired/revoked/exhausted code는 동일한 sanitized 결과를 내고 원문·digest를 log/event에 남기지 않는다.
- Concurrent last-use 경쟁에서 `max_uses`를 초과하지 않는다.
- Link 또는 counter 갱신 실패 시 inactive user를 포함한 signup transaction 전체가 rollback된다.

### 13.4 Password/email verification

- Password setup은 `is_active` 또는 signup status를 변경하지 않는다.
- Verification token의 만료, single-use, replay 방지 및 request/user binding을 검증한다.
- Email verification은 `pending_email_verification -> pending_approval`만 수행하고 login을 허용하지 않는다.
- Password, token, invitation 원문 및 민감 식별자가 log, event, validation payload에 나타나지 않는다.

### 13.5 Membership 및 guard regression

- Join approval은 signup approval을 대체하지 않는다.
- Membership approval은 active account에만 가능하다.
- Signup approval만으로 `join_requests`, `user_group_map`, `employee_profile`이 생성되지 않는다.
- Existing inactive/missing account join approval은 user, membership, token 및 approved request write를 만들지 않는다.
- 기존 Issue 3A/3B/3D guard인 inactive login 차단, inactive/missing 기존 session 차단, inactive membership/group tenant 차단, role/permission cache freshness 및 lookup-only 경로의 no-provisioning을 유지한다.
- 기존 active user의 정상 login과 정상 membership approval은 regression 없이 유지한다.

테스트는 가능한 한 DB-free unit test로 service contract와 guard를 먼저 고정하고, 별도 격리된 central test DB에서 transaction, constraint, routing, concurrency 및 migration을 검증한다. 실제 운영성 DB나 tenant 실데이터를 테스트에 사용하지 않는다.

## 14. Rollout 위험

| 위험 | 영향 | 완화책 |
|---|---|---|
| `users` default 의존 | pending account가 active로 생성될 수 있음 | 생성 시 `is_active=false` 명시, transaction test |
| Login/session guard 회귀 | 미승인 account 접근 | write path enable 전 3A/3B/3D regression gate |
| Request 승인과 activation 부분 성공 | 상태 원장과 login 가능 여부 불일치 | row lock/version과 단일 central transaction |
| Duplicate/concurrent signup | 중복 user 또는 여러 open request | canonical email, DB unique/partial unique, 오류 매핑 |
| Invitation race | 최대 사용량 초과 | row lock 또는 atomic conditional update |
| Invitation 비밀 노출 | account targeting 및 code 재사용 | keyed digest, generic error, log redaction, rate limit |
| Central/tenant routing 오류 | tenant DB에 잘못된 schema/write | server-owned alias, router test, tenant migration deny |
| Legacy account 잘못된 backfill | 허위 승인 이력 및 운영 혼선 | legacy active user를 그대로 인정, fabricated backfill 금지 |
| Approval과 membership UI 혼합 | 운영자 오승인 및 권한 집중 | 별도 route/service/permission과 명확한 상태 표시 |
| Notification 실패 | 승인됐지만 안내 누락 또는 중복 | commit 이후 retry 가능한 delivery 처리 |
| 개인정보 장기 보존 | 법적·운영 위험 | retention/redaction 정책을 enable 전 확정 |
| Event/현재 상태 drift | 감사 복원 실패 | 동일 transaction, invariant/reconciliation 진단 설계 |

## 15. Rollback 및 운영 주의사항

- 기능 rollback은 feature flag로 signup 생성, decision 및 invitation validation을 disable하고 이미 생성된 table과 request/event를 보존하는 방식이 기본이다.
- 데이터가 들어간 signup/event table을 drop하는 reverse migration은 자동 실행하지 않는다. 삭제는 별도 백업·보존·승인 절차가 필요한 destructive operation이다.
- Migration 전 승인된 central DB backup과 restore readiness를 준비한다. 이번 이슈에서는 backup 또는 DB 작업을 수행하지 않는다.
- Write enable 후 application 구버전으로 rollback할 때 새 inactive user가 남을 수 있다. 구버전이 이를 active로 간주하거나 join approval로 provisioning하지 않는지 사전 검증한다.
- Request가 approved인데 user가 inactive인 경우는 후속 suspension인지 transaction drift인지 구분해야 한다. 자동 재활성화하지 않고 event와 account administration 근거를 진단한다.
- 기존 active account에는 signup row가 없을 수 있으며 이는 정상 legacy 상태다. 운영 화면에서 "승인 이력 없음"을 "미승인"으로 오해하지 않게 한다.
- Terminal request 개인정보의 retention/redaction, inactive orphan user 처리, 이메일 재사용 및 계정 삭제는 자동 cascade가 아닌 별도 승인 정책으로 둔다.
- Event 및 관리자 note에는 secret, password, token, invitation 원문, 실제 email/UUID/session 값 또는 raw payload를 넣지 않는다.
- Metrics와 alert는 상태별 건수, 전이 실패, invitation validation 실패율처럼 집계·비식별 값만 사용한다.
- Rollout 중에도 기존 `join_requests`, `central_repo.create_user`, `user_group_map` write 및 Django admin 정책을 signup 우회 경로로 사용하지 않는다.

## 16. 다음 구현 이슈 분리안

### Issue 4B: Central signup schema migration draft

- Exact columns/types/lengths, constraints, indexes, FK 삭제 정책 및 managed ownership 확정
- `signup_requests`와 `signup_request_events` additive migration draft
- Invitation schema를 같은 migration chain에 포함할지 결정
- Central-only router, fresh/upgrade/rollback test 설계
- Migration 파일 작성까지만 수행하고 실제 migrate와 운영 DB 변경은 별도 승인으로 분리

### Issue 4C: Signup request service and form hardening

- Input normalization, password validation, generic duplicate 처리 및 rate limiting
- Inactive user + request + initial event atomic creation
- Terms/privacy evidence와 bounded field validation
- Optional invitation service interface만 연결하고 approval/membership은 제외

### Issue 4D: Account approval/rejection admin flow

- 별도 account-decision permission 및 server-side authorization
- Expected-state/version, row locking, idempotent approve/reject
- Request event와 `users.is_active` activation의 atomic transaction
- Join Requests 및 Django admin 정책과 분리된 UI/service

### Issue 4E: Invitation code validation and audit

- Code generation, normalization, keyed digest/key rotation 계약
- Expiry/revocation/use-limit concurrency 및 provenance event
- Generic public error, rate limit, redaction 및 sanitized telemetry
- Suggested membership가 auto approval/write로 이어지지 않는 테스트

### Issue 4F: Password setup and email verification alignment

- Verification/setup token lifecycle, expiry, replay 방지 및 delivery retry
- `pending_email_verification -> pending_approval` 전이
- Password/email verification과 activation의 분리 불변조건
- 승인 전후 password setup UX 및 기존 account 호환성

Issue 진행 순서는 4B schema 계약 확정 후 4C와 4F의 service contract를 정렬하고, 4D account decision을 연결한 다음 4E invitation을 독립 enable하는 안을 권장한다. 각 이슈는 코드 변경 범위, migration 실행 여부, DB 접근 여부를 별도로 승인받아야 한다.

## 17. Implementation readiness 결론

GeoFlow Phase 1 signup 구현은 **inactive central user와 authoritative signup request를 같은 transaction에서 만들고, email verification과 account approval을 분리하며, 승인 transaction에서만 `users.is_active=true`로 전이하는 구조**를 기준으로 준비한다. Invitation과 membership은 각각 provenance/suggestion 및 별도 membership approval 경계에 머물러야 한다.

Schema 방향과 migration 순서는 구현 초안을 시작할 만큼 정리되었지만, Issue 4B 착수 전에 managed ownership, exact type/constraint, FK 삭제 정책, retention/redaction, inactive user 재신청·삭제, 승인 전 이메일 변경, invitation release/use 복구 정책을 명시적으로 확정해야 한다. 이 gate가 해결되기 전에는 production migration, signup write enable 또는 account approval endpoint를 배포하지 않는다.
