# Join Request Approval and Account Provisioning Policy Audit

## 1. 조사 범위

이 문서는 현재 join request 승인 흐름과 중앙 account provisioning, `user_group_map` 활성화 및 password setup의 경계를 정적으로 감사한다. 조사 대상은 다음과 같다.

- `control.views_join.join_request_decide_view`
- `central_repo.get_join_request`와 상태 변경 helper
- `central_repo.get_or_create_user_by_email` 및 `create_user`
- `central_repo.upsert_user_group_membership`
- password 존재 확인과 setup token 발급
- requested email, group 및 requested role 처리
- existing active, existing inactive 및 missing user의 차이
- Issue 3A/3B/3D-1 guard가 제공하는 방어 범위
- 현재 schema 검증 문서에 기록된 `users.is_active` default

코드, DB, migration, endpoint 및 browser는 변경하거나 실행하지 않았다. 실제 user, email, UUID, token 및 credential 값은 조회하거나 기록하지 않았다.

## 2. 현재 join request approval 흐름

승인 view는 central admin decorator와 POST 제한을 적용한 뒤 다음 순서로 동작한다.

1. request id로 `join_requests` row를 읽는다.
2. `requested_email`, `group_id`, `requested_role_code`를 사용한다.
3. 현재 관리자의 중앙 user id를 email 기준 get-or-create로 구한다.
4. reject이면 join request 상태만 rejected로 변경한다.
5. approve이면 requested email의 중앙 user를 get-or-create한다.
6. requested role code를 role id로 변환한다.
7. `user_group_map`을 기본 status `active`로 upsert한다.
8. join request를 approved로 변경한다.
9. user에게 password가 없으면 setup token을 생성하고 안내 메일을 보낸다.

이 흐름은 account approval 상태를 조회하지 않는다. 요청의 현재 status가 pending인지 view에서 명시적으로 확인하지 않으며, user 생성, membership upsert, request 상태 변경, token 생성 및 메일 전송을 하나의 원자적 transaction으로 묶지 않는다.

대상 identity는 join request의 `requested_email`을 기준으로 결정된다. 조회 결과의 requester user id는 반환되지만 approval 대상 user 선택에는 사용되지 않는다. role은 `requested_role_code`를 별도 조회해 결정하며, role이 유효하지 않더라도 missing user 생성은 이미 발생한 뒤일 수 있다.

## 3. Existing active user 처리

requested email과 일치하는 중앙 user가 이미 있으면 `get_or_create_user_by_email`은 기존 id를 반환한다. `is_active`는 변경하지 않는다.

기존 user가 active인 경우:

- role이 유효하면 active `user_group_map`이 생성 또는 갱신된다.
- password가 이미 있으면 setup token을 발급하지 않는다.
- password가 없으면 setup token을 발급한다.
- 이미 인증 session이 있다면 Issue 3D-1이 다음 tenant 요청에서 새 active membership을 확인하므로 tenant 접근이 가능해질 수 있다.
- 새 로그인에서도 Issue 3A의 active account gate와 active membership 조건을 통과할 수 있다.

이는 join request가 기존 승인 account에 그룹·역할 membership을 부여하는 용도라는 정책과 대체로 일치한다. 다만 request status, group 상태, role 상태, 승인 transaction 및 중복 승인에 대한 별도 검증은 필요하다.

분류: **B - 정책 확정 후 안전 조건을 구현**.

## 4. Existing inactive user 처리

기존 inactive user도 email lookup으로 발견되므로 새 user를 만들지 않는다. 현재 join approval은 `users.is_active`를 갱신하지 않지만 active `user_group_map`은 만들 수 있다.

결과는 다음과 같다.

- account는 inactive 상태로 유지된다.
- membership은 active가 될 수 있다.
- password가 없으면 setup token을 받을 수 있다.
- password setup은 password hash와 email verification을 변경할 수 있지만 account를 활성화하지 않는다.
- Issue 3A는 inactive user의 신규 login을 차단한다.
- Issue 3B는 이미 존재하는 session에서 inactive 또는 missing central user를 차단한다.
- Issue 3D-1은 account guard를 통과한 뒤에만 tenant membership을 평가하므로 inactive account는 tenant에 진입하지 못한다.

기술적 접근 차단은 작동하지만 account approval 전에 active membership이 존재해 lifecycle 의미가 불명확해진다. account가 나중에 활성화되면 별도 membership 검토 없이 기존 active membership이 즉시 효력을 가질 수 있다.

분류: **B - active account만 membership 승인 대상으로 제한할 정책 구현 필요**.

## 5. Missing user 처리

requested email에 해당하는 중앙 user가 없으면 `central_repo.get_or_create_user_by_email`이 `create_user`를 호출한다. `create_user`의 INSERT는 id, email, name 및 timestamp만 명시하고 다음 중요 필드를 명시하지 않는다.

- `is_active`
- `email_verified`
- `password_hash`

검증된 현재 중앙 schema metadata에 따르면 `users.is_active` default는 true, `email_verified` default는 false, `password_hash` default는 empty text다. 따라서 missing user는 현재 schema에서 active account로 생성될 수 있다.

그 뒤 join approval은 active membership을 만들고 password setup token을 발급한다. setup 완료 후 account는 이미 active이고 password가 설정되므로 signup approval 없이 login 및 tenant 접근 조건을 모두 갖출 수 있다.

또한 role code가 유효한지 확인하기 전에 user를 생성하므로 invalid role 요청에서도 active orphan account가 남을 가능성이 있다.

분류: **A - signup schema 도입 전 즉시 차단할 위험**.

## 6. User 생성 시 `is_active` 결정 방식

`central_repo.create_user`는 `is_active`를 SQL에 명시하지 않는다. unmanaged Django model에도 default true가 선언되어 있고, 실제 schema 검증 결과 역시 DB default true다.

그러므로 현재 join approval의 missing-user activation semantics는 service 정책이 아니라 DB default에 의존한다. schema default가 바뀌면 같은 코드의 보안 의미가 달라지고, 현재 상태에서는 join approval이 active account provisioning 경로로 동작한다.

이 결정은 코드에서 명시적이지 않고 UI, permission 이름, 감사 이력에도 privileged account provisioning으로 표현되지 않는다.

분류: **A - implicit active provisioning 제거 필요**.

## 7. `user_group_map` activation 시점

`upsert_user_group_membership`의 기본 status는 active다. join approval은 account state를 확인하지 않고 이 기본값을 사용한다.

현재 activation 시점은 join request approve action과 동일하지만 다음과 원자적으로 묶이지 않는다.

- user 생성 또는 기존 account 상태 확인
- join request 상태 전이
- password token 생성
- mail 발송

따라서 중간 실패 시 다음 partial state가 가능하다.

- user만 생성되고 membership은 없음
- membership은 active지만 request status 갱신 실패
- request는 approved지만 token 또는 mail 실패
- 반복 승인으로 role 또는 token 상태가 다시 변경됨

권장 원칙은 account approval을 먼저 확정하고, active account에 대한 membership 승인 transaction에서만 `user_group_map.status='active'`를 기록하는 것이다.

분류: **A - precondition 보강**, **D - signup schema 이후 transaction 재설계**.

## 8. Password setup token 발급 흐름

membership 승인 후 `user_has_password`가 password hash의 존재와 비어 있지 않음을 확인한다. password가 없으면 다음을 수행한다.

- raw setup token 생성
- `user_tokens`에 token과 expiry 저장
- account password setup URL 구성
- requested email로 안내 발송

현재 canonical password setup은 password hash와 `email_verified=true`를 갱신하지만 `is_active`를 변경하지 않는다. 따라서 existing inactive user는 setup 후에도 login이 차단된다.

그러나 missing user는 DB default로 active 생성될 수 있으므로 setup 완료 후 즉시 login 가능해진다. password setup이 account approval을 대신하지 않는다는 메시지와 view 동작만으로는 이 upstream provisioning 위험을 막을 수 없다.

token 저장 방식과 schema 통합은 이번 정책 audit 범위 밖이지만, token 발급은 account 상태가 명시적으로 허용된 경우에만 수행해야 한다.

## 9. Issue 3A/3B/3D-1 guard가 막는 범위

| guard | 차단하는 범위 | 차단하지 못하는 범위 |
|---|---|---|
| Issue 3A | inactive central user의 신규 login/session 생성 | DB default로 active 생성된 missing user |
| Issue 3B | inactive 또는 missing central user의 기존 session | active로 생성된 user의 session |
| Issue 3D-1 | inactive/missing membership, inactive group, alias mismatch | active account와 active membership 조합 자체 |
| Issue 3D-2 | stale role/permission cache 재사용 | 원장에서 active로 승인된 잘못된 membership |
| Issue 3D-3 | 인증·인가 lookup 중 implicit user 생성 | join approval의 명시적 get-or-create provisioning |

따라서 지금까지의 guard는 existing inactive user를 안전하게 차단하지만, join approval이 missing user를 active로 생성하는 경우에는 우회를 막지 못한다. 각 guard는 authoritative state를 정확히 집행할 뿐, 잘못 생성된 authoritative state를 구별할 수 없다.

## 10. Account approval 우회 가능성

현재 코드와 검증된 schema 조합에서는 다음 우회 chain이 가능하다.

1. missing requested email을 포함한 join request 승인
2. DB default true에 따른 active central user 생성
3. active `user_group_map` 생성
4. password setup token 발급
5. password setup 완료와 email verification
6. Issue 3A login active gate 통과
7. Issue 3D-1 tenant membership gate 통과

이는 join request approval이 account signup approval과 membership approval을 동시에 수행하는 효과를 낸다. 현재 별도 signup request 원장이 없기 때문에 승인 근거와 상태 전이도 명확히 남지 않는다.

결론: **실제 account approval 우회 가능성이 있으며 A 등급의 즉시 hardening 대상이다.**

## 11. Option A/B/C/D 비교

| 선택지 | 장점 | 주요 위험/비용 | Phase 1 판단 |
|---|---|---|---|
| A. 기존 provisioning 유지 | 기존 운영 흐름 보존, 한 번의 승인으로 onboarding 가능 | join request가 account approval을 대체하고 active default에 의존, 감사·권한 경계 불명확 | 권장하지 않음. 유지 시 privileged 예외 문서와 강한 permission/audit 필요 |
| B. existing approved/active user만 승인 | account와 membership 경계가 가장 명확, schema 변경 없이 fail-closed 가능 | missing/inactive 대상 onboarding이 signup approval 준비 전 중단될 수 있음 | **Phase 1 권장안** |
| C. inactive user와 pending account/request 생성 | 장기 제품 모델과 잘 맞고 onboarding 정보를 보존 | signup request schema와 pending membership 모델, transaction 설계 필요 | signup schema 이후 권장 |
| D. privileged admin provisioning으로 재정의 | 기존 one-step 운영을 명시적으로 유지 가능 | 고위험 권한, UI 구분, 감사 이력, atomic transaction 및 별도 승인 필요 | 별도 제품 결정 전 보류 |

Option A는 현재 동작을 설명할 수는 있지만 확정 제품 원칙과 충돌한다. Option D는 가능하지만 일반 join approval과 같은 endpoint와 permission으로 제공해서는 안 된다. Option C는 장기 구조로 적합하나 아직 필요한 authoritative signup schema가 없다.

## 12. 권장 정책

### Phase 1 결정: Option B

join request approval은 **이미 존재하며 명시적으로 active인 중앙 account**에 대해서만 active membership을 부여한다.

- missing user이면 join approval을 완료하지 않는다.
- inactive user이면 join approval을 완료하지 않는다.
- missing/inactive 대상은 account signup/approval 절차가 필요하다는 sanitized 상태로 유지한다.
- join request는 pending 또는 별도 non-approved 상태를 유지하며 active `user_group_map`을 만들지 않는다.
- password setup token은 join approval에서 missing/inactive account를 위해 발급하지 않는다.
- password setup, email verification 및 invitation은 account approval을 대신하지 않는다.
- account가 승인·활성화된 뒤 membership approval을 별도 수행한다.

기존 고객 흐름에 missing-user one-step onboarding 의존성이 있는지는 코드만으로 확인할 수 없다. 구현 전 운영 담당자가 그 사용 여부를 확인해야 한다. 의존성이 있다면 Option A를 조용히 유지하지 말고 별도 Option D privileged provisioning 이슈로 분리한다.

## 13. Phase 1 최소 hardening 제안

다음 변경은 schema 변경 없이 좁게 구현할 수 있다.

1. approve action의 첫 단계에서 requested email로 existing user를 lookup-only 조회한다.
2. user가 없으면 user, membership, token을 만들지 않고 요청을 미승인 상태로 유지한다.
3. existing user의 `is_active`가 정확히 true인지 확인한다.
4. inactive이면 membership upsert와 token 발급을 수행하지 않는다.
5. role과 group의 유효성 및 active 상태를 user/membership write 전에 확인한다.
6. join request가 pending인지 확인하고 이미 결정된 요청의 반복 승인을 막는다.
7. 승인 성공 시 account state를 변경하지 않는다는 테스트를 둔다.
8. 가능한 범위에서 membership upsert와 request status 전이를 동일 central transaction으로 묶는다. 메일 발송은 commit 이후 처리한다.
9. 실패 메시지와 로그에는 account 존재 여부를 불필요하게 노출하지 않는다.
10. 관리자 결정자 identity는 Issue 3D-3 lookup-only helper 원칙에 맞게 existing central user만 사용한다.

즉시 막아야 할 최소 위험은 missing user creation과 inactive user의 active membership 생성이다. transaction 통합과 UI 개선은 그 다음 단계로 분리할 수 있다.

## 14. Signup schema 이후 재설계 항목

signup schema가 도입되면 Option C 형태로 account와 membership lifecycle을 명시적으로 연결한다.

- signup request를 account approval authoritative workflow로 사용
- 가입 시 user를 명시적 `is_active=false`로 생성
- approval과 `users.is_active=true`를 동일 transaction에서 처리
- join request는 account approval 이후 membership 승인 대상으로 처리
- invitation의 suggested group/role과 실제 membership activation을 분리
- account 승인 전 membership suggestion 또는 pending link가 필요하면 별도 상태로 저장
- immutable signup 및 membership decision event 기록
- actor, reason, timestamp 및 이전/이후 상태 감사
- password setup token은 승인 정책에 맞는 시점에만 발급
- membership upsert와 join request 상태 전이의 idempotency/locking
- mail은 transaction commit 이후 전송하고 실패 재시도 가능하게 설계
- 개인정보 보존, 거절, 철회 및 재신청 정책 반영

`join_requests`를 signup request 원장으로 재사용하지 않는다.

## 15. 필요한 테스트 목록

### 현재 흐름 characterization

1. existing active user 승인 시 새 user를 생성하지 않음
2. existing active user 승인 시 requested role의 active membership 생성
3. password가 있는 active user에는 setup token 미발급
4. password가 없는 active user에 대한 token 정책 확인
5. existing inactive user의 `is_active`를 변경하지 않음
6. 현재 missing user path가 get-or-create를 호출하는 위험을 고정하는 audit/static test

### Phase 1 Option B hardening

7. missing user 승인 시 user 생성 없음
8. missing user 승인 시 membership/token/request-approved write 없음
9. inactive user 승인 시 membership 생성 없음
10. inactive user 승인 시 password token 발급 없음
11. active user만 membership 승인 가능
12. role invalid 또는 inactive이면 user/membership write 없음
13. group inactive이면 membership write 없음
14. non-pending request 재승인 차단
15. reject path는 account나 membership을 생성하지 않음
16. account `is_active`와 `email_verified`는 join approval에서 변경하지 않음
17. partial failure 시 membership과 request 상태가 불일치하지 않음
18. mail 실패가 committed authorization state를 되돌리거나 중복 생성하지 않음

### Guard regression

19. inactive account login 차단 유지
20. inactive/missing account 기존 session 차단 유지
21. inactive membership/group tenant 차단 유지
22. role/permission cache freshness 유지
23. lookup-only 인증·인가 경로에서 provisioning 없음

## 16. 다음 Codex 구현 이슈 제안

### Issue 3D-4A: Join approval existing-active-account precondition

가장 먼저 구현한다.

- requested user를 lookup-only로 조회
- missing 또는 inactive이면 fail-closed
- user 생성, membership upsert 및 token 발급 금지
- pending request와 active role/group 확인
- 기존 active user의 정상 membership 승인 유지
- DB-free unit test와 기존 guard regression 실행

### Issue 3D-4B: Join approval transaction and idempotency hardening

- membership upsert와 request approved 전이를 하나의 transaction으로 묶음
- row locking 또는 조건부 status update로 중복 승인 방지
- mail을 commit 이후 처리
- partial failure 및 retry 테스트

### Issue 3D-4C: Privileged provisioning policy decision

운영상 missing-user one-step onboarding이 반드시 필요할 때만 Option D를 별도 설계한다.

- 일반 join approval과 다른 permission 및 UI
- user를 명시적 inactive 또는 명시적으로 승인된 상태로 생성하는 정책
- 이중 승인 또는 강화된 central admin 권한
- immutable audit
- setup token과 account activation의 명확한 순서

### Signup schema 이후

Option C 기반으로 signup approval과 membership suggestion/approval을 연결하되 authoritative store는 분리한다.

최종 결론은 account approval과 membership approval을 분리하는 것이다. Phase 1에서는 missing/inactive central user에 대한 join approval을 active membership provisioning으로 사용하지 않고, existing active account에 대한 membership 승인만 허용하는 Option B가 가장 안전하다.
