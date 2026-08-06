# Privileged Missing-user Provisioning Policy Decision

## 1. 조사 범위

이 문서는 missing central user에 대해 계정 생성과 그룹 membership 부여를 함께 수행하는 privileged provisioning이 GeoFlow에 필요한지 정책적으로 검토한다. 다음 자료와 현재 구현을 정적으로 확인했다.

- `docs/planning/GeoFlow_Product_Structure_v1.md`
- `collaboration/05_Phase1_Account_Signup/09_join_request_account_provisioning_policy_audit.md`
- `collaboration/05_Phase1_Account_Signup/03_signup_invitation_schema_design.md`
- `control/views_join.py`
- `control/services/central_repo.py`
- `control/decorators.py`
- `control/templates/control/join_requests_pending.html`
- `control/urls.py`

코드와 데이터베이스는 변경하지 않았다. 데이터베이스 조회, migration, endpoint 또는 browser 실행도 수행하지 않았다.

## 2. 현재 Phase 1 join approval 상태

Issue 3D-4A와 3D-4B가 반영된 현재 일반 join approval은 다음 경계를 가진다.

1. 요청은 `pending` 상태여야 한다.
2. 요청 role과 group이 유효하고 group이 active여야 한다.
3. requested email에 대응하는 central user가 이미 존재하고 `is_active=true`여야 한다.
4. missing 또는 inactive user이면 user 생성, membership upsert, password setup token 발급 및 request approval을 수행하지 않는다.
5. existing active user에 대해서만 active `user_group_map`과 request의 `approved` 전이를 같은 central transaction에서 처리한다.
6. password setup token과 안내 메일은 승인 transaction 성공 이후의 후속 처리다.
7. 일반 approval은 `users.is_active` 또는 account approval 상태를 변경하지 않는다.

따라서 현재 일반 join approval은 account provisioning이 아니라 existing active account에 대한 membership approval이다. 이는 account approval과 membership approval을 분리한다는 Phase 1 정책에 부합한다.

## 3. Privileged missing-user provisioning의 정의

Privileged missing-user provisioning은 일반 사용자의 group join request 승인이 아니다. 중앙 user가 없는 대상을 위해 고권한 운영자가 다음 작업 일부 또는 전부를 명시적으로 수행하는 별도 onboarding workflow다.

- central `users` row 생성
- account 상태와 승인 근거 설정
- email verification 및 password setup lifecycle 시작
- group 및 role suggestion 또는 membership 승인
- 모든 결정의 actor, reason, 시각 및 상태 전이 기록

이 flow는 lookup 중 발생하는 silent get-or-create와 구분되어야 한다. 특히 DB default에 기대어 active account를 만들거나 일반 join approval endpoint에서 account와 membership을 함께 활성화하는 동작은 privileged provisioning으로 인정할 수 없다.

## 4. 일반 join approval과 privileged provisioning의 차이

| 구분 | 일반 join approval | privileged missing-user provisioning |
|---|---|---|
| 대상 account | existing, active central user만 | missing central user |
| 주된 목적 | group 및 role membership 승인 | account onboarding과 후속 membership 준비 |
| account 생성 | 금지 | 별도 정책과 권한 아래에서만 가능 |
| `users.is_active` 변경 | 금지 | signup/account approval 정책에 따라 명시적으로 결정 |
| membership | 승인 transaction에서 active 가능 | account approval 전에는 active로 만들지 않는 것이 원칙 |
| UI | 기존 Join Requests 승인/거절 | 별도 화면과 명확한 고위험 경고 필요 |
| permission | 현재 central admin (`is_staff`) | 별도 provisioning permission 필요 |
| 감사 수준 | join decision 기록 | immutable account/provisioning/decision events 필요 |
| 실패 시 처리 | membership과 request 상태 rollback | account, request, event, membership 경계를 포함한 원자성 필요 |

현재 join request UI는 한 행에 승인과 거절만 제공하며 대상 account의 존재 상태나 account provisioning 의도를 구분하지 않는다. 이 UI에 privileged provisioning을 추가하면 서로 다른 승인 의미가 섞이고 운영자의 오승인 위험이 커진다.

## 5. Option 1/2/3/4 비교

| 선택지 | 장점 | 위험 및 선행 조건 | 분류 | 판단 |
|---|---|---|---|---|
| Option 1. Phase 1에서 제공하지 않음 | 가장 작은 공격 표면, 현재 3D-4A/4B 경계 유지, schema 불필요 | missing user onboarding은 signup/account approval을 먼저 거쳐야 함 | A | **Phase 1 권장** |
| Option 2. 별도 flow에서 inactive account만 생성 | account와 membership 승인을 분리하고 향후 signup flow와 연결 가능 | signup request 원장, pending membership 표현, event와 별도 permission이 현재 없음 | B/C | signup schema 이후 검토 |
| Option 3. active account와 active membership 동시 생성 | one-step onboarding 편의 | account approval 우회, 과도한 권한 집중, 잘못된 대상·role 동시 활성화, 복구와 감사 복잡성 | C/D | Phase 1 비권장 |
| Option 4. signup schema 이후 invitation 기반으로 재설계 | authoritative signup state, invitation provenance, 분리된 approval 및 immutable event를 함께 제공 | schema, migration, rollout 및 운영정책 선행 필요 | B/E | 장기 권장 |

Option 2는 임시 구현으로 만들기보다 Option 4의 일부로 구현하는 편이 안전하다. Option 3은 기술적으로 가능해도 현재 제품 원칙과 가장 크게 충돌하며, 일반 join approval에 결합해서는 안 된다.

## 6. 보안 위험 분석

### Account approval 우회

missing user를 active로 생성하고 membership까지 활성화하면 join approval이 signup/account approval을 사실상 대체한다. password setup이 이어질 경우 계정 승인 근거 없이 로그인과 tenant 접근 조건이 완성될 수 있다.

### 권한 집중과 오승인

현재 `require_central_admin`은 central user의 `is_staff`만 확인한다. account 생성, activation, role assignment를 모두 허용하기에는 너무 넓고 목적이 불명확한 권한이다. 별도 permission 없이 one-step provisioning을 제공하면 중앙 관리자 credential 하나가 account와 tenant 권한을 동시에 부여할 수 있다.

### 상태 불일치

account, signup state, password setup, membership 및 감사 event가 서로 다른 단계에서 부분 성공하면 활성 계정만 남거나 승인 근거 없는 membership이 남을 수 있다. 현재 signup workflow 원장이 없으므로 안전한 재시도와 rollback 기준도 충분하지 않다.

### Identity 및 대상 혼동

일반 join request 화면은 requested email과 group/role 요청을 보여 주지만 privileged account 생성에 필요한 명시적 identity 확인, 중복 account 처리, 승인 사유 및 정책 확인을 제공하지 않는다. 같은 승인 버튼으로 두 의미를 처리하면 잘못된 대상을 생성할 위험이 있다.

### 비밀번호와 token lifecycle 혼동

Password setup과 email verification은 account approval이 아니다. token 발급 시점이 account activation과 불명확하게 연결되면 운영자와 사용자 모두 비밀번호 설정 완료를 계정 승인으로 오해할 수 있다.

## 7. 운영 편의성 분석

One-step onboarding은 운영자가 한 화면에서 계정과 membership을 만들 수 있어 초기 처리 시간은 줄인다. 그러나 현재 코드만으로 실제 운영이 이 방식에 의존하는지는 확인할 수 없다. 운영 편의를 이유로 일반 join approval에 silent provisioning을 되돌리는 것은 다음 비용을 만든다.

- 잘못 생성된 account와 membership을 정정하는 별도 절차
- account 승인 근거와 membership 승인 근거를 사후 재구성하는 비용
- token 또는 mail 실패 시 수동 복구
- 과도한 중앙 관리자 권한 통제와 감사 부담
- 중복 신청, 재시도 및 동시 승인 처리 복잡성

Phase 1에서는 missing user에게 먼저 signup/account approval을 완료하도록 안내하고, 이후 기존 join request를 다시 승인하는 두 단계 절차가 더 안전하다. 운영상 one-step 흐름이 반드시 필요하다는 확인은 별도 제품 결정으로 받아야 한다.

## 8. Audit 및 permission 요구사항

향후 privileged flow를 도입하려면 최소한 다음 조건이 필요하다.

### Permission

- 일반 membership approval과 다른 전용 permission codename
- 단순 `is_staff`가 아닌 명시적 server-side permission 검사
- account activation과 membership assignment 권한을 필요하면 별도로 분리
- 자기 승인, 과도한 role 부여 및 대상 group 범위를 제한하는 정책
- 고위험 운영에서는 request actor와 approver 분리 또는 이중 승인 검토

### Audit

- immutable provisioning 및 signup decision event
- actor central user id, reason code, timestamp, 이전/이후 상태 기록
- account 생성, activation, invitation 연결, membership suggestion 및 membership activation을 서로 구분
- 비밀번호, token, invitation 원문, session 값 또는 request payload 전체를 기록하지 않음
- 일반 `audit_events`는 보조 security log로만 사용하고 workflow 상태 원장으로 사용하지 않음

### UI 및 운영 통제

- 일반 Join Requests와 분리된 route, view 및 template
- missing account 생성임을 명확히 알리는 확인 단계
- 생성될 account 상태와 membership 상태를 실행 전에 표시
- 중복 또는 existing account 발견 시 자동 전환하지 않고 중단
- idempotency key 또는 조건부 상태 전이와 재시도 정책
- 메일은 commit 이후 전송하고 실패를 재시도 가능한 후속 상태로 기록

현재 구조는 이 요구사항을 충족하지 않는다.

## 9. Signup schema와의 관계

현재 검증된 central schema에는 authoritative `signup_requests`, `invitation_codes`, `signup_request_events` 및 `signup_invitation_events`가 없다. `users.is_active`는 로그인 가능 여부만 표현하며 신청 lifecycle 전체를 설명하지 못한다. `join_requests`는 group과 role 요청용이고 signup 원장으로 재사용하면 안 된다.

권장 schema가 도입되면 privileged onboarding은 다음 순서를 따라야 한다.

1. 명시적 privileged action으로 `users`를 `is_active=false`로 생성한다.
2. 같은 transaction에서 authoritative `signup_requests`와 initial event를 만든다.
3. invitation이 있으면 원문을 저장하지 않고 provenance와 suggestion만 연결한다.
4. account approval은 signup request 상태와 `users.is_active=true`를 같은 transaction에서 변경한다.
5. membership suggestion은 account approval과 구분해 보존한다.
6. account가 active가 된 뒤 별도 권한 검사를 거쳐 `user_group_map`을 활성화한다.
7. password setup과 email verification은 승인 상태를 대신하지 않는다.

이 구조라면 Option 2를 안전하게 표현할 수 있고, 운영 정책이 요구할 때만 강하게 통제된 Option 3 변형을 별도 검토할 수 있다.

## 10. 권장 정책

Phase 1에서는 privileged missing-user provisioning을 구현하지 않는다.

- 일반 join approval은 existing active central account에 대한 membership approval로 유지한다.
- missing user는 signup/account approval flow를 먼저 완료한다.
- inactive user는 account approval 또는 별도 account administration 없이 active membership을 받지 않는다.
- 현재 join request UI, endpoint 및 `require_central_admin` 권한에 account 생성 기능을 추가하지 않는다.
- silent get-or-create active account provisioning을 되살리지 않는다.
- one-step onboarding이 반드시 필요하다는 운영 결정이 내려져도 별도 privileged flow로만 설계한다.
- 별도 flow 구현은 signup schema, immutable event, 전용 permission 및 명시적 `is_active` 정책이 준비된 뒤 재검토한다.

이는 Option 1을 Phase 1 결정으로 채택하고 Option 4를 장기 권장안으로 보류하는 결정이다.

## 11. Phase 1에서 구현하지 않을 항목

- missing user를 join approval에서 생성하는 기능
- DB default에 의존한 active account 생성
- active account와 active membership의 one-step 생성
- 일반 Join Requests 화면에 privileged provisioning 버튼 추가
- 기존 `require_central_admin`만으로 account provisioning 허용
- account activation 전 active membership 생성
- password setup 또는 email verification을 account approval로 간주
- `join_requests` 또는 `audit_events`를 signup authoritative store로 재사용
- pending account/membership을 임시 문자열 상태나 session으로 표현
- `central_repo.create_user`를 일반 join approval에 다시 연결

## 12. Signup schema 이후 재검토할 항목

- Option 2 기반 inactive account provisioning의 제품 필요성
- invitation 기반 관리자 onboarding과 일반 public signup의 관계
- account approval과 membership suggestion/approval의 UI 단계
- 전용 provisioning 및 account-activation permission 체계
- 이중 승인 필요 role과 group 범위
- immutable signup/provisioning event schema
- account, request 및 event의 atomic creation과 idempotency
- password setup token 및 email verification 순서
- 거절, 철회, 만료, 재신청 및 개인정보 보존 정책
- 기존 legacy active account와 새 signup workflow의 rollout 방식
- 운영상 one-step 활성화가 정말 필요한지에 대한 명시적 승인

## 13. 필요할 경우 후속 구현 이슈 목록

### Signup schema implementation

- 승인된 설계에 따라 `signup_requests`, invitation 및 immutable event schema를 별도 migration 이슈로 구현한다.
- inactive login/session guard가 유지되는지 rollout 전 검증한다.

### Signup/account approval service

- signup request state 전이와 `users.is_active` 변경을 원자적으로 처리한다.
- account activation permission, reason 및 actor 기록을 구현한다.

### Membership suggestion handoff

- invitation 또는 privileged onboarding의 group/role suggestion을 active `user_group_map`과 분리한다.
- active account에 대해서만 별도 membership approval을 허용한다.

### Privileged provisioning permission and UI

- 운영 필요성이 승인된 경우에만 일반 Join Requests와 분리된 route와 화면을 만든다.
- 전용 permission, 경고, 재확인, 범위 제한 및 필요 시 이중 승인을 구현한다.

### Audit and recovery

- immutable event, idempotency, commit 이후 notification 및 실패 재시도 정책을 구현한다.
- partial failure와 concurrent approval에 대한 DB-free 및 integration test를 추가한다.

## 14. 최종 결정 문구

**GeoFlow Phase 1에서는 privileged missing-user provisioning을 구현하지 않는다. 일반 join approval은 existing active central account에 대한 membership approval로만 유지한다. Missing user는 signup/account approval flow로 처리한다. One-step onboarding이 향후 반드시 필요하다고 결정되면 일반 join approval과 분리된 privileged flow로 설계하며, signup schema, immutable audit event, 전용 permission, 명시적 account activation 정책 및 안전한 transaction 경계가 준비된 이후에만 구현을 재검토한다.**

