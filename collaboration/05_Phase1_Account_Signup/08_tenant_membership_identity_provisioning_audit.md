# Tenant Membership and Identity Provisioning Hardening Audit

## 1. 조사 범위

이 문서는 Issue 3A/3B/3C 이후 남은 tenant authorization freshness와 중앙 identity provisioning 경계를 정적으로 감사한다. 조사 대상은 다음과 같다.

- 로그인 시 tenant candidate 생성
- group search와 group selection
- tenant connection 준비 및 등록된 alias 재사용
- `TenantMiddleware`, `CentralGuardMiddleware`, `GFAuthzContextMiddleware`
- `user_group_map`, roles, permissions 및 session cache
- `ensure_user_from_request`와 관련 identity helper
- `central_repo.create_user` 및 `get_or_create_user_by_email`
- join request 승인과 membership 생성
- membership, group, role 변경 후 기존 session 반영 여부

코드, DB, migration, endpoint 및 browser는 변경하거나 실행하지 않았다. employee profile은 조사 대상 identity 또는 authorization 원장으로 취급하지 않았다.

## 2. 현재 tenant candidate 생성 흐름

기본 웹 로그인은 다음 순서로 진행된다.

1. 중앙 `users`에서 password hash와 `is_active`를 조회한다.
2. `is_active`가 정확히 true인 경우에만 password 검증과 Django session 생성을 진행한다.
3. `central_repo.list_tenants_for_user`가 `user_group_map`, `groups`, `group_db_config`를 조인해 후보를 반환한다.
4. `_selectable_tenant_candidates`가 중앙 ORM으로 candidate별 membership과 group/config를 다시 조회한다.
5. `_candidate_is_selectable`이 membership status `active`, group status `active`, 필수 connection metadata 및 alias 일치를 검사한다.

`list_tenants_for_user` 자체 SQL에는 membership status와 group status 조건이 없지만, 현재 기본 login flow에서는 후속 `_selectable_tenant_candidates`가 이를 보완한다. eligibility lookup 예외는 빈 후보로 처리되어 fail-closed다.

따라서 **기본 로그인 시 최초 candidate 생성은 active `user_group_map`과 active group만 선택 가능하게 만드는 구조**다. 다만 이 보장은 candidate 생성 시점에 한정되며 이후 session 후보의 freshness를 보장하지 않는다.

분류: **D - 최초 후보 필터는 현재 구현으로 충분**, **B - 후보 생성과 선택 사이 freshness는 후속 구현 필요**.

## 3. 현재 group selection 흐름

여러 후보가 있으면 `tenant_candidates` 전체가 session에 저장되고 group selection 화면은 이 session 목록을 표시한다. 선택 요청은 다음을 수행한다.

- `ensure_user_from_request`로 중앙 user id를 얻는다.
- 요청된 group id가 session의 `tenant_candidates`에 있는지만 확인한다.
- session에 group id, alias 및 compatibility key를 기록한다.
- 현재 중앙 DB에서 role 목록을 다시 읽어 session `roles`에 저장한다.
- `tenant_candidates`를 제거하고 post-login redirect로 이동한다.

문제는 선택 시점에 `user_group_map.status`, group status, config 존재 및 alias 일치를 다시 확인하지 않는다는 점이다. login과 선택 사이에 membership 또는 group이 비활성화되면 오래된 session candidate가 선택될 수 있다. role 조회는 inactive membership이면 빈 목록을 반환하지만, 빈 role은 tenant 진입 자체를 차단하지 않는다.

또한 `ensure_user_from_request`는 이름과 달리 lookup-only helper가 아니므로 group selection에서 중앙 user가 없을 때 새 active user를 생성할 가능성이 있다. Issue 3B가 일반 authenticated `/control/` 요청의 missing central user를 먼저 차단하지만 helper 자체의 provisioning side effect는 다른 호출 경로와 향후 middleware 순서 변경에 취약하다.

분류: **A - 선택 직전 live membership/group 재검증 필요**, **A - lookup 경로의 implicit provisioning 제거 필요**.

## 4. 현재 tenant connection 준비 흐름

`post_login_redirect`와 tenant 경로의 `TenantMiddleware`는 `ensure_tenant_connection_for_session`을 호출한다. 중앙 alias이거나 tenant group id가 없는 경우를 제외하면 함수는 다음 두 branch로 나뉜다.

### 4.1 alias가 아직 등록되지 않은 경우

- `ensure_user_from_request`로 중앙 user id를 구한다.
- active `user_group_map` 존재 여부를 확인한다.
- active group에 연결된 `GroupDBConfig`를 조회한다.
- session alias와 config alias 일치 및 필수 connection metadata 완전성을 검사한다.
- 검사를 통과한 뒤 alias를 runtime connection registry에 등록한다.

이 branch는 membership과 group을 검사하지만 lookup helper가 user를 생성할 수 있다는 별도 문제가 있다.

### 4.2 alias가 이미 등록된 경우

alias가 `connections.settings`에 존재하면 connection handler가 resolve되는지만 확인하고 즉시 성공한다. 이 branch에서는 다음을 검사하지 않는다.

- 현재 authenticated central user와 session group의 active membership
- group active status
- session group과 registered alias의 현재 metadata 일치
- membership role 변경 또는 삭제

runtime connection registry는 process 범위에서 재사용될 수 있으므로, 한 번 등록된 alias가 이후 요청의 authorization을 대신하게 된다. 이는 connection availability와 access authorization을 혼동한 것이다.

분류: **A - 즉시 hardening 필요**.

## 5. 현재 role, permission 및 `gf_authz_ctx` cache 흐름

권한 정보는 여러 session key와 request cache에 분산되어 있다.

- 기본 login과 group selection은 `roles`를 session에 저장한다.
- `perms_context`는 `roles`가 없을 때만 중앙 DB에서 읽고 이후 session 값을 재사용한다.
- template ACL tag는 `perms`가 있으면 우선 사용하고, 없을 때만 중앙 DB에서 읽어 저장한다.
- `GFAuthzContextMiddleware`는 `gf_authz_ctx`가 없을 때만 roles, permissions, project ids를 로드하고 `gf_roles`, `gf_perms`에도 복제한다.
- 이후 요청은 session context를 request-level set으로 복사한다.

명시적인 TTL, membership version, role version, group status version 또는 매 요청 freshness 검사는 없다. `gf_load_user_context`의 membership 조건은 status가 null이거나 active인 row를 허용하며 group active status는 확인하지 않는다. 이는 다른 helper의 exact `status='active'` 기준과도 일치하지 않는다.

`clear_tenant_session_state`는 `roles`와 candidate/group key 일부를 제거하지만 `perms`, `gf_authz_ctx`, `gf_roles`, `gf_perms`는 제거하지 않는다. Issue 3B의 account fail-closed는 logout으로 전체 auth session을 철회하지만, tenant connection 실패나 membership 철회의 cleanup 경로는 동일한 수준의 cache 제거를 보장하지 않는다.

분류: **A - membership 철회 시 모든 tenant/authz cache 제거**, **B - role/permission freshness 또는 versioning 설계**.

## 6. Membership 변경 후 기존 session 반영 여부

active membership이 inactive 또는 deleted 상태로 바뀌어도 기존 session에는 group id, alias, roles 및 permissions context가 남을 수 있다.

- alias가 미등록이면 connection 준비 과정의 exact active check로 차단될 수 있다.
- alias가 이미 등록되어 있으면 membership query가 생략되어 기존 tenant session이 계속 진행될 수 있다.
- session `roles`, `perms`, `gf_authz_ctx`, `gf_roles`, `gf_perms`는 membership 변경으로 자동 무효화되지 않는다.
- 일부 permission helper는 DB를 직접 조회해 inactive membership을 차단하지만, session 우선 helper는 오래된 권한을 사용할 수 있다.

따라서 현재 구조는 membership 철회를 다음 요청에 일관되게 반영하지 않는다.

분류: **A - 즉시 hardening 필요**.

## 7. Group 비활성화 후 기존 session 반영 여부

최초 candidate 생성과 미등록 alias branch는 active group을 확인한다. 그러나 다음 경우에는 group 비활성화가 즉시 반영되지 않는다.

- group selection이 과거 session candidate만 신뢰하는 경우
- alias가 이미 connection registry에 존재하는 경우
- `gf_authz_ctx`가 session에 남아 있는 경우
- `roles` 또는 `perms`가 session cache에 남아 있는 경우

`CentralGuardMiddleware`는 central alias 여부로 tenant URL을 차단할 뿐 membership 또는 group 상태를 조회하지 않는다. `TenantMiddleware`가 freshness guard 역할을 해야 하지만 registered alias fast path 때문에 현재는 완전하지 않다.

분류: **A - 즉시 hardening 필요**.

## 8. Registered tenant alias 재사용 위험

등록된 alias는 DB connection 설정의 존재 여부일 뿐 현재 request user의 authorization 증거가 아니다. 동일 process에서 다른 요청이 이미 등록한 alias일 수도 있으며, membership 철회나 group 비활성화 후에도 registry entry가 남을 수 있다.

최소 원칙은 다음과 같다.

- authorization check는 alias 등록 여부보다 먼저 수행한다.
- active central account, active membership, active group 및 session group/alias binding을 request마다 확인한다.
- authorization 성공 후에만 기존 connection을 재사용하거나 새 connection을 등록한다.
- connection registration helper는 availability를 담당하고 membership guard는 authorization을 담당하되, 우회 방지를 위해 connection helper 내부에도 방어적 검증을 유지한다.

분류: **A - registered alias fast path 수정 필요**.

## 9. `ensure_user_from_request`의 lookup/provisioning 경계

`ensure_user_from_request`는 현재 lookup-only가 아니다.

- Django auth user email로 중앙 user를 찾고 없으면 `users` row를 `is_active=TRUE`로 INSERT한다.
- email이 없으면 legacy id lookup을 시도한다.
- email 형태의 username이 있으면 역시 중앙 user를 `is_active=TRUE`로 생성한다.

이 helper는 tenant connection, group selection, central admin decorator, context processor 및 template permission tag에서 사용된다. 조회나 authorization을 기대하는 코드가 암묵적으로 account provisioning과 DB write를 수행할 수 있다. 이는 중앙 `users`가 승인된 로그인 원장이고 lookup helper가 인증 과정에서 user를 자동 생성하면 안 된다는 원칙에 직접 위배된다.

별도로 `services_identity.get_or_create_user_by_email`은 inactive row를 생성하며, `central_repo.create_user`는 `is_active`를 명시하지 않고 DB default에 의존한다. 동일한 이름과 유사 목적의 helper가 서로 다른 activation semantics를 갖는다.

분류: **A - authorization 경로에서 lookup-only helper로 교체**, **E - provisioning service 통합은 장기 refactor**.

## 10. Join request approval과 account activation 경계

현재 join approval은 다음을 한 흐름에서 수행한다.

1. 대상 email로 중앙 user를 get-or-create한다.
2. role을 찾는다.
3. `user_group_map`을 기본 active 상태로 upsert한다.
4. join request를 approved로 변경한다.
5. password가 없으면 password setup token을 만들고 안내한다.

이 흐름은 대상 user의 account approval 상태 또는 `users.is_active`를 확인하지 않는다. missing user는 `central_repo.create_user`를 통해 생성되며 activation 결과가 DB default에 의존한다. 중앙 관리자 결정자 identity에도 get-or-create가 사용된다.

Issue 3A/3B는 inactive account의 login/session을 막지만, active membership이 account approval보다 먼저 존재하는 것을 막지는 않는다. DB default가 active라면 join approval이 사실상 account 생성과 activation까지 우회할 위험이 있고, default가 inactive라도 승인된 membership이 미리 생성되어 account/membership lifecycle 경계가 흐려진다.

또한 `create_or_pending_membership`에는 allowed domain에 따른 active membership 자동 upsert 경로가 존재한다. 현재 호출 위치는 people 관련 흐름이지만, 명시적 승인 원칙과의 관계를 별도로 결정해야 한다.

분류: **A - join approval에서 missing user 자동 active provisioning 방지**, **C - inactive account에 membership을 미리 허용할지 정책 결정**.

## 11. `user_group_map`과 signup/account approval의 관계

권장 authoritative boundary는 다음과 같다.

- `users`와 signup workflow는 account 존재 및 활성 상태를 결정한다.
- `user_group_map`은 승인된 user-group-role 연결만 나타낸다.
- account approval과 membership approval은 별도 결정이며 한 상태가 다른 상태를 암묵적으로 변경하지 않는다.
- tenant 접근에는 `users.is_active=true`, active `user_group_map`, active group이 모두 필요하다.
- invitation, password setup, email verification 또는 join approval 어느 하나도 나머지 조건을 대체하지 않는다.
- employee profile은 이 판정에 사용하지 않는다.

inactive account에 active membership을 미리 기록할지는 정책적으로 선택할 수 있지만, tenant access guard는 반드시 account와 membership을 모두 검사해야 한다. 더 명확한 Phase 1 기본안은 account approval 전에는 active membership을 만들지 않고 join request를 pending 상태로 유지하는 것이다.

## 12. 위험 분류표

| 위험 또는 현재 상태 | 분류 | 근거 | 권장 조치 |
|---|---|---|---|
| login candidate의 active membership/group 필터 | D | 후속 eligibility 검사 존재 | 회귀 테스트 유지 |
| group selection의 session candidate 신뢰 | A | 선택 시 live membership/group 미검사 | 선택 직전 재검증 |
| registered alias fast path | A | membership/group query 생략 | authorization을 registry check보다 먼저 수행 |
| membership 철회 후 기존 session | A | alias 및 cache가 남을 수 있음 | 다음 tenant 요청에서 fail-closed 및 cleanup |
| group 비활성화 후 기존 session | A | registered alias/cache가 상태를 우회 | active group 재검증 |
| `roles`/`perms` cache stale | A | session 우선, 자동 무효화 없음 | membership denial 시 전부 제거 |
| `gf_authz_ctx` 장기 freshness | B | TTL/version 없음 | request reload 또는 version/TTL 설계 |
| authz query의 null membership status 허용 | B | exact active 정책과 불일치 | status semantics 확정 후 통일 |
| `ensure_user_from_request` implicit active creation | A | lookup 호출이 account INSERT 수행 | lookup/provision 분리 |
| `central_repo.create_user` DB default 의존 | A | activation semantics가 schema default에 좌우됨 | 명시적 inactive provisioning만 허용 |
| 중복 identity helper semantics | E | helper별 active default가 다름 | 별도 service refactor |
| join approval의 missing user 생성 | A | account approval과 membership approval 혼합 | 기존 approved account lookup 요구 |
| inactive account에 active membership 선생성 | C | 접근은 guard되나 lifecycle 의미 불명확 | 제품 정책 결정 |
| allowed-domain membership auto approval | C | 명시적 승인 원칙과 충돌 가능 | 유지·제거 정책 결정 |
| `CentralGuardMiddleware` | D | central alias의 tenant URL 차단 역할 수행 | membership guard로 오해하지 않도록 유지 |
| DB lookup 비용 | B | request별 central query 비용 증가 | 우선 correctness, 이후 짧은 TTL/version 최적화 |

## 13. 최소 hardening 위치 제안

### 13.1 Primary guard: `TenantMiddleware` 이전 또는 내부

Issue 3B account guard 이후, tenant connection 준비와 thread-local 설정 전에 tenant membership freshness guard를 실행하는 것이 가장 안전하다. tenant-scoped 요청마다 다음을 하나의 중앙 read-only lookup으로 확인한다.

- authenticated central user id
- `users.is_active=true`
- session group과 active `user_group_map` 일치
- group status active
- session alias와 group DB config alias 일치

실패 또는 lookup 예외 시 tenant session과 모든 role/permission cache를 제거하고 중앙 route로 fail-closed한다. API 요청은 sanitized 401 또는 403, HTML 요청은 안전한 중앙 경로로 처리한다.

### 13.2 Defense in depth: tenant connection helper

`ensure_tenant_connection_for_session`은 alias가 이미 등록된 경우에도 authorization 검사를 생략하지 않아야 한다. primary guard가 있더라도 connection helper가 독립 호출될 수 있으므로 방어적 검증을 유지한다.

### 13.3 Group selection

session candidate를 선택하기 직전에 동일한 live membership/group/config binding을 재검증한다. 실패 시 candidate와 tenant state를 제거하고 재로그인 또는 안전한 중앙 화면으로 보낸다.

### 13.4 Cache cleanup

공통 cleanup helper는 최소한 다음을 제거해야 한다.

- tenant alias 및 compatibility key
- group id/UUID
- tenant candidates
- `roles`, `perms`
- `gf_authz_ctx`, `gf_roles`, `gf_perms`
- request-level authz cache가 생성되기 전 차단

### 13.5 Identity lookup

authorization code는 `find_central_user_from_request`와 같은 lookup-only helper만 사용해야 한다. provisioning은 명시적인 command/service와 승인 workflow에서만 수행하고, 생성 시 account status를 명시해야 한다.

### 13.6 비용과 보안 균형

Phase 1 최소 patch에서는 tenant-scoped request마다 단일 indexed central lookup을 수행하는 편이 안전하다. 정확성이 검증된 뒤 membership/group `updated_at` 또는 authorization version을 session과 비교하는 짧은 TTL cache를 검토할 수 있다. process-global alias registry나 무기한 session cache를 authorization 근거로 사용해서는 안 된다.

## 14. 필요한 테스트 목록

### Membership freshness guard

1. anonymous 및 public path의 기존 동작 유지
2. active account + active membership + active group은 downstream 진행
3. missing membership은 tenant downstream 차단
4. inactive/deleted membership은 차단
5. inactive group은 차단
6. membership lookup exception은 fail-closed
7. session group과 alias/config 불일치는 차단
8. 이미 등록된 alias도 membership/group을 재검증
9. inactive 처리 후 tenant/group/candidate/role/permission cache 전체 제거
10. HTML과 API 응답 shape 검증
11. 중앙 `/control/` 요청은 tenant membership lookup 없이 정상 처리
12. Issue 3B account guard가 membership guard보다 먼저 실행됨을 정적 검증

### Group selection

13. session candidate가 있어도 live inactive membership이면 선택 거부
14. group inactive 또는 config alias mismatch이면 선택 거부
15. live active candidate는 기존 redirect와 session 설정 유지

### Authorization cache

16. role 변경 후 오래된 `gf_authz_ctx`가 재사용되지 않음
17. membership 철회 시 `roles`, `perms`, `gf_*` key가 제거됨
18. exact active status만 권한에 반영됨

### Identity provisioning

19. lookup-only helper는 missing central user에 INSERT하지 않음
20. tenant connection, decorator, context processor 및 template tag가 provisioning을 호출하지 않음
21. 명시적 provisioning은 inactive 상태를 지정하고 별도 승인 없이 membership을 만들지 않음

### Join approval

22. existing active account에만 membership 승인 허용 또는 선택된 정책대로 동작
23. inactive/missing account에서 account를 자동 활성화하지 않음
24. join approval과 account approval transaction 경계 검증
25. 기존 active user의 login, single/multi tenant routing 회귀 유지

## 15. 구현 이슈 분리안

최소 patch와 장기 refactor를 한 번에 섞지 않는다.

### 최소 hardening

- tenant request membership/group freshness guard
- registered alias fast path 제거 또는 재검증
- denial 시 전체 tenant/authz cache cleanup
- group selection 직전 live revalidation

### 후속 hardening

- role/permission context reload와 cache invalidation
- lookup-only identity helper 도입 및 호출처 교체
- join approval의 account state precondition

### 장기 refactor

- 중복 identity service 통합
- authorization version 또는 TTL cache
- account approval과 membership approval event/transaction 모델
- project membership까지 포함한 통합 authorization context

## 16. 다음 Codex 작업 제안

### Issue 3D-1: Tenant membership freshness guard

가장 먼저 수행한다. Issue 3B 이후, tenant connection 및 `GFAuthzContextMiddleware` 이전에 active membership, active group, alias binding을 재검증한다. registered alias도 예외로 두지 않는다. 실패 시 전체 tenant/authz cache를 제거하고 fail-closed한다.

### Issue 3D-2: Role and permission cache invalidation hardening

`roles`, `perms`, `gf_authz_ctx`, `gf_roles`, `gf_perms`의 생성·사용·삭제를 하나의 정책으로 통합한다. Phase 1에서는 tenant request마다 reload하거나 membership freshness guard 성공 후 재구성하는 단순 정책을 우선 검토한다.

### Issue 3D-3: Identity lookup and provisioning separation

`ensure_user_from_request`를 lookup-only helper와 explicit provisioning service로 분리한다. authorization, middleware, template 및 decorator에서는 INSERT를 금지한다. `central_repo.create_user`의 DB default 의존도 제거하고 신규 account는 명시적 inactive 상태로만 생성하도록 별도 설계한다.

### Issue 3D-4: Join request approval and account provisioning policy decision

join approval이 기존 approved account만 대상으로 해야 하는지, inactive account에 pending membership을 미리 기록할지 결정한다. missing user 자동 생성, active membership upsert, password setup 발송의 순서를 signup approval 정책과 정렬한다. allowed-domain auto approval 경로도 함께 분류한다.

### 권장 실행 순서

1. Issue 3D-1 membership freshness guard
2. Issue 3D-2 cache invalidation
3. Issue 3D-3 identity lookup/provisioning 분리
4. Issue 3D-4 join approval 정책 결정 및 후속 구현

결론적으로 현재 가장 큰 즉시 위험은 registered alias가 authorization 재검증을 건너뛰는 점과 session 권한 cache가 membership/group 변경 후 남는 점이다. 첫 구현은 기존 active user 흐름을 유지하면서 tenant-scoped 요청의 active membership, active group 및 alias binding을 매번 중앙 원장에서 확인하는 좁은 fail-closed guard여야 한다.
