# GeoFlow Product Structure v1

작성일: 2026-08-05
상태: 추가개발 전 제품 구조 v1 확정안

## 1. 문서 목적

이 문서는 GeoFlow의 추가개발에 앞서 중앙관리, 테넌트 업무, 사용자와 직원, 가입 승인, 기준정보, 프로젝트 접근 제어의 경계를 확정한다. 구현 상세나 특정 화면 시안이 아니라 이후 모델·권한·메뉴·API 작업이 따라야 할 제품 구조 기준이다.

기준 자료는 다음과 같다.

- `collaboration/04_Product_Structure_Planning/01_ai_review_request.md`
- `collaboration/04_Product_Structure_Planning/claude_opinion.md`
- `collaboration/04_Product_Structure_Planning/gemini_opinion.md`
- `collaboration/04_Product_Structure_Planning/deepseek_opinion.md`
- `collaboration/04_Product_Structure_Planning/04_current_structure_audit.md`

외부 검토 의견이 서로 다르거나 사용자 최종 결정과 충돌하는 경우 사용자 최종 결정을 우선한다.

## 2. v1 핵심 원칙

1. 중앙은 신원, 인증, 테넌트 소속, 역할, 권한, 승인, 중앙 표준 기준정보를 관리한다.
2. 테넌트는 계약, 프로젝트, 직원·인력 정보, 업무 이벤트, 업무분류, 지도, 파일, 보고서 등 운영 데이터를 관리한다.
3. 중앙 `users`가 로그인 가능한 사람의 유일한 계정 원장이다.
4. 테넌트 `employee_profile`은 직원·인력 관리 데이터이며 로그인 계정이나 권한 원장이 아니다.
5. 권한의 기준은 중앙 `users + user_group_map + roles + role_permissions + permissions`이다.
6. 프로젝트 접근은 테넌트 역할과 프로젝트 배정을 결합하고 기본 거부 방식으로 적용한다.
7. 중앙 카탈로그와 테넌트 업무분류는 목적이 다른 별도 기준정보다.
8. 초대코드는 가입 경로와 승인 근거를 추적하지만 승인 자체를 대신하지 않는다.
9. 목록, 상세, API, 파일, 이벤트 등 동일한 프로젝트에 속하는 모든 객체에 같은 접근 정책을 적용한다.
10. UI에서 메뉴를 숨기는 것만으로 권한을 구현하지 않는다. 서버의 query와 object-level 검사에서 강제한다.

## 3. 중앙관리와 테넌트 페이지 분리 원칙

### 3.1 중앙관리의 책임

중앙관리는 전체 플랫폼 관점의 데이터만 다룬다.

- 중앙 계정 생성, 승인, 활성화와 비활성화
- 그룹·테넌트 소속 관리
- 테넌트 역할과 권한 템플릿 관리
- 가입 요청과 역할 요청 처리
- 초대코드 발급·검증·사용 이력 관리
- 그룹과 테넌트 연결 metadata 관리
- 중앙 표준 카탈로그와 공통 코드 관리
- 보안·권한·승인 변경 감사
- 플랫폼 운영 상태와 테넌트 상태 확인

중앙 화면에서 테넌트의 계약·프로젝트·직원·업무 데이터를 직접 편집하지 않는다. 운영 지원 목적으로 상태를 보여줄 필요가 있다면 기본적으로 집계 또는 read-only 진단으로 제한한다.

### 3.2 테넌트 페이지의 책임

테넌트 페이지는 선택된 하나의 테넌트 범위에서 실제 업무를 수행한다.

- 계약과 협력사
- 프로젝트와 프로젝트 참여자
- 직원·인력 프로필
- 업무 이벤트와 업무분류
- 지도와 시설물
- 파일과 사진
- 보고서와 현황
- 테넌트 운영 설정

테넌트 화면은 중앙 계정을 새 권한 원장으로 복제하지 않는다. 테넌트 역할 확인은 중앙 권한 context를 사용한다.

### 3.3 경계 강제

- 중앙 app은 central DB로, 운영 app은 선택된 tenant DB로 라우팅한다.
- tenant context가 없거나 유효하지 않으면 tenant 업무 query를 수행하지 않는다.
- URL parameter나 request payload로 tenant alias를 선택하지 않는다.
- 중앙 관리자 권한과 테넌트 관리자 권한을 같은 의미로 취급하지 않는다.
- cross-tenant 일괄 변경은 별도 승인된 운영 도구가 없는 한 허용하지 않는다.

## 4. 중앙 메뉴 구조

| 1차 메뉴 | 주요 기능 | 기본 접근 주체 |
|---|---|---|
| 중앙 대시보드 | 사용자·승인·그룹·테넌트 운영 현황 | platform admin |
| 사용자 관리 | 사용자 목록·상세·상태·비밀번호 재설정 | platform admin |
| 가입·승인 관리 | 회원가입, 그룹 가입, 역할 요청 승인·반려 | platform admin, 위임된 승인자 |
| 그룹 관리 | 그룹 정보, 사용자 소속, 그룹 상태 | platform admin |
| 테넌트 연결 관리 | 그룹과 tenant DB metadata, 연결 상태 | 제한된 platform operator |
| 역할·권한 관리 | 역할, permission, 기본 권한 매트릭스 | platform admin |
| 초대코드 관리 | 발급, 만료, 사용 이력, 승인 근거 | 승인 정책상 허용된 관리자 |
| 중앙 카탈로그 | 표준 분류, 표준 코드, 시설물 표준 | catalog admin |
| 감사·시스템 | 승인·권한 변경 이력, 보안 이벤트, 서비스 상태 | platform admin, auditor |

그룹은 논리적 소속 단위이고 tenant DB는 데이터 격리 단위이므로 UI와 도메인 용어에서 구분한다. v1에서 실제 관계가 1:1이더라도 같은 개념으로 합치지 않는다.

## 5. 테넌트 메뉴 구조

| 1차 메뉴 | 하위 기능 |
|---|---|
| 대시보드 | 내 프로젝트, 최근 업무, 최근 파일, 주요 현황 |
| 계약 관리 | 계약 목록·상세·등록, 협력사 연결 |
| 협력사 관리 | 협력사 목록·상세 및 관련 정보 |
| 프로젝트 관리 | 프로젝트 목록·상세, 참여자, 업무범위 |
| 업무 관리 | 업무 이벤트 목록·등록·수정, 내 업무, 지연 업무 |
| 지도 관리 | 통합지도, 프로젝트 지도, 시설물 |
| 파일·사진 | 프로젝트·이벤트·시설물 첨부와 현장사진 |
| 직원·인력 관리 | 직원 프로필, 조직·부서·직책 정보, 중앙 계정 연결 상태 |
| 보고서 | 프로젝트 현황과 허용된 내보내기 |
| 시스템 설정 | 업무분류, tenant 운영 코드, 일반 설정, 역할 요청 관리 |
| 내 정보 | 중앙 계정 정보, 내 소속·역할·프로젝트 접근 범위 확인 |

메뉴 노출은 역할과 permission에 따라 달라지지만, 메뉴가 보이지 않는 것과 서버 접근이 거부되는 것은 별도로 구현·검증한다.

## 6. 중앙 User와 Tenant `employee_profile` 관계

### 6.1 역할 구분

| 구분 | 중앙 `users` | tenant `employee_profile` |
|---|---|---|
| 목적 | 로그인 신원과 계정 | 직원·인력 업무정보 |
| 로그인 가능 여부 | 가능 | 자체적으로 불가 |
| 권한 원장 | 예 | 아니오 |
| 주요 식별자 | 중앙 user UUID | tenant employee UUID |
| 필수 존재 여부 | 접속자에게 필수 | 모든 접속자에게 필수 아님 |
| 계정 없는 인력 표현 | 해당 없음 | 가능 |

### 6.2 연결 정책

- 직원이 시스템 권한을 필요로 하지 않으면 `employee_profile`만 존재할 수 있다.
- 직원이 접속 권한을 필요로 하면 중앙 계정을 생성하거나 기존 중앙 계정 연결을 요청한다.
- 연결은 `employee_profile.central_user_id` 같은 명시적 soft link를 사용한다.
- 중앙 DB와 tenant DB 사이에 물리적 FK를 가정하지 않는다.
- 이메일은 최초 연결 후보 탐색에 사용할 수 있지만 영구 권한 키로 사용하지 않는다.
- 권한 판정은 항상 중앙 user UUID를 기준으로 한다.
- tenant `employee_profile.role_code`는 인증·인가의 authoritative value로 사용하지 않는다. 유지한다면 인사 표시값 또는 중앙 역할의 비권위 캐시라는 의미를 명시해야 한다.
- 연결, 재연결, 해제에는 승인과 감사 이력이 필요하다.

## 7. 회원가입, 초대코드, 승인 정책

### 7.1 회원가입 원칙

- 회원가입은 중앙 계정 후보를 만든다.
- 신규 계정은 승인 전 제한 상태로 둔다.
- 중앙 계정 승인과 특정 그룹·역할 승인은 논리적으로 구분한다.
- 그룹 소속과 역할은 승인된 `user_group_map`으로만 부여한다.
- 직원 프로필을 회원가입과 동시에 자동 생성하지 않는다.

### 7.2 초대코드 정책

- 초대코드는 선택사항이다.
- 초대코드가 없어도 정상 가입·승인 요청 경로를 제공한다.
- 초대코드는 가입 경로, 초대한 주체, 예정 그룹 또는 역할, 승인 근거를 추적하는 용도다.
- 유효한 초대코드가 있어도 계정이나 그룹 소속을 자동 승인하지 않는다.
- 초대코드 자체에 권한을 내장하거나 클라이언트가 이를 신뢰하게 하지 않는다.
- 만료, 사용 가능 횟수, 활성 상태, 발급자, 사용자를 추적한다.
- 저장 시 원문 노출을 최소화하고 검증 실패는 일반화된 메시지로 처리한다.

### 7.3 권장 흐름

1. 사용자가 기본 가입정보와 선택적 초대코드를 제출한다.
2. 중앙 계정은 승인 대기 상태로 생성된다.
3. 초대코드가 있으면 검증 결과와 발급 근거가 요청에 연결된다.
4. 승인자가 계정 승인 여부를 결정한다.
5. 필요한 그룹과 역할을 별도로 승인한다.
6. `user_group_map`이 생성 또는 갱신된다.
7. 직원 데이터와 연결할 필요가 있으면 별도의 연결 승인 절차를 수행한다.
8. 모든 승인·반려·역할 변경을 감사한다.

## 8. 카탈로그와 업무분류·이벤트의 경계

### 8.1 중앙 카탈로그

중앙 카탈로그는 플랫폼 전체에서 의미가 같아야 하는 표준 기준정보다.

- 표준 분류체계
- 공통 코드와 표준 명칭
- 시설물·업무범위의 공통 기준
- 테넌트 간 통계와 교환의 기준 ID

중앙 카탈로그 항목은 tenant가 직접 수정·삭제하지 않는다.

### 8.2 테넌트 업무분류

업무분류는 tenant의 실제 운영 기준정보다.

- tenant별 업무 대분류·중분류
- 표시 순서와 활성 상태
- 현장 또는 조직별 운영 용어
- 업무 이벤트 입력 시 사용하는 분류

업무분류 변경은 과거 이벤트 의미를 훼손하지 않도록 삭제보다 비활성화를 우선한다.

### 8.3 업무 이벤트

업무 이벤트는 기준정보가 아니라 transaction data다.

- 특정 프로젝트 또는 업무범위에서 발생한 사실
- 상태, 일정, 담당, 메모, 첨부 등 실행 데이터
- 생성·수정·삭제 권한과 감사가 필요한 데이터

업무분류 관리는 시스템 설정에, 이벤트 실행은 업무 관리에 둔다.

### 8.4 선택적 매핑

- tenant 업무분류는 필요한 경우 중앙 카탈로그 항목과 매핑할 수 있다.
- 매핑은 동일성 선언이 아니라 통계·검색·보고를 위한 명시적 관계다.
- 하나의 중앙 항목에 여러 tenant 분류가 연결될 수 있는지, 미분류 처리, 매핑 버전 정책은 구현 전에 확정한다.
- v1 초기에는 중앙 표준과 tenant 분류를 분리 운영하고, 실제 통합 통계 요구가 확인된 범위부터 매핑한다.

## 9. 프로젝트 접근 정책

### 9.1 권한 계산 원칙

프로젝트 접근은 다음 두 층으로 계산한다.

```text
tenant role permission
        +
project assignment when required
        =
effective project access
```

- tenant role은 중앙 `user_group_map.role_id`에서 결정한다.
- 프로젝트 배정 대상은 중앙 `users.id`를 기준으로 한다.
- `employee_profile.id`는 권한 주체로 사용하지 않는다.
- 명시되지 않은 접근은 거부한다.

### 9.2 역할별 프로젝트 범위

| 역할 | 프로젝트 범위 |
|---|---|
| `tenant_admin` | tenant의 전체 프로젝트 |
| `manager` | tenant의 전체 프로젝트 |
| `project_admin` | tenant의 전체 프로젝트 조회·운영 |
| `project_coordinator` | tenant의 전체 프로젝트 조회, 활성 project membership 프로젝트 운영 |
| `worker` | 활성 project membership으로 지정된 프로젝트만 |
| `view_only` | 활성 project membership으로 지정된 프로젝트만, 읽기 전용 |
| `guest` | 활성 project membership으로 지정된 프로젝트만, 제한적 읽기 |

tenant 전체 프로젝트 조회는 `tenant_admin`, `manager`, `project_admin`, `project_coordinator`에게 허용한다. `project_admin`은 전체 프로젝트를 운영하고, `project_coordinator`는 활성 project membership으로 지정된 프로젝트만 운영한다. 프로젝트 참여 역할 `project_manager`, `project_leader`, `worker`, `viewer`는 중앙 tenant 역할과 별개로 `prj.project_members`에 저장한다.

### 9.3 적용 범위

프로젝트 접근 검사는 다음 위치에 동일하게 적용한다.

- 프로젝트 목록 query
- 프로젝트 상세와 JSON/API
- 프로젝트 수정·삭제
- 프로젝트 참여자 관리
- 해당 프로젝트의 업무 이벤트
- 프로젝트·이벤트 첨부파일과 presigned URL
- 프로젝트 지도 객체와 시설물
- 프로젝트 보고서와 내보내기
- contract를 통해 프로젝트에 도달하는 간접 경로

지도 객체, 시설물, 파일, 업무 이벤트와 보고서는 각각 독립적인 공개 범위를 갖지 않는다. 모두 자신이 속한 상위 `project_id`의 접근 범위를 상속한다. 직접 URL, API, 검색, 다운로드 또는 presigned URL 경로에서도 상위 프로젝트를 서버에서 역추적하여 동일한 접근 검사를 수행한다.

클라이언트가 보낸 project ID만 신뢰하지 않고 서버에서 실제 상위 project와 접근권한을 다시 확인한다. project scope를 확인할 수 없는 하위 객체는 기본적으로 접근을 거부한다.

### 9.4 직원·구성원 정보 접근 경계

- `employee_profile`은 로그인 또는 권한 주체가 아니라 tenant의 직원·인력 관리 데이터다.
- 전체 직원·구성원 목록과 직원 상세 관리 메뉴는 `tenant_admin`, `manager` 또는 명시적인 직원관리 permission이 있는 사용자만 접근한다.
- `project_coordinator`, `project_leader`, `worker`, `view_only`, `guest`는 역할만으로 전체 직원·구성원 목록을 볼 수 없다. 프로젝트 참여자 조회는 참여 프로젝트 범위로 제한한다.
- 위 역할은 기본적으로 자신의 계정, 소속, 역할과 연결된 내 정보만 볼 수 있다.
- 지정 프로젝트 상세 안에서는 그 프로젝트의 참여자 목록을 조회할 수 있다.
- 프로젝트 참여자 목록은 이름, 프로젝트 역할, 소속 표시명, 참여 상태 등 업무 수행에 필요한 제한된 필드만 제공한다.
- 프로젝트 참여자 조회를 통해 연락처, 인사정보, 주민등록 관련 정보, 다른 프로젝트 참여 여부 또는 전체 직원 디렉터리를 추론할 수 없어야 한다.
- 직원관리 permission은 프로젝트 접근권한과 별개이며, project membership만으로 획득되지 않는다.

## 10. 역할별 권한 매트릭스 요약

기호: `A` 전체 범위, `P` 지정 프로젝트 범위, `R` 읽기 전용, `-` 기본 거부. 실제 구현은 permission codename으로 세분화한다.

| 기능 | tenant_admin | manager | project_admin | project_coordinator | worker | view_only | guest |
|---|---:|---:|---:|---:|---:|---:|---:|
| tenant 기본정보 조회 | A | A | A | A | R | R | 제한 R |
| tenant 설정 변경 | A | permission 필요 | - | - | - | - | - |
| 사용자 소속·역할 관리 | A | permission 필요 | - | - | - | - | - |
| 전체 프로젝트 목록·상세 | A | A | - | - | - | - | - |
| 지정 프로젝트 목록·상세 | A | A | P | P | P | P/R | P/제한 R |
| 프로젝트 생성 | permission 필요 | permission 필요 | permission 필요 | permission 필요 | - | - | - |
| 프로젝트 수정 | permission 필요 | permission 필요 | P + permission | P + permission | P + permission | - | - |
| 프로젝트 삭제 | 제한된 permission | 제한된 permission | P + 제한된 permission | - | - | - | - |
| 프로젝트 참여자 배정 | permission 필요 | permission 필요 | P + permission | P + permission | - | - | - |
| 지정 프로젝트 참여자 제한 조회 | A | A | P/R | P/R | P/R | P/R | P/제한 R |
| 계약·협력사 조회 | A | A | 연결 프로젝트 범위 | 연결 프로젝트 범위 | 연결 프로젝트 범위 | R | 제한 R |
| 계약·협력사 변경 | permission 필요 | permission 필요 | P + permission | P + permission | - | - | - |
| 업무 이벤트 조회 | A | A | P | P | P | P/R | P/제한 R |
| 업무 이벤트 생성·수정 | permission 필요 | permission 필요 | P + permission | P + permission | P + permission | - | - |
| 파일 조회·다운로드 | A | A | P + permission | P + permission | P + permission | P/R | P + 제한 permission |
| 파일 업로드·삭제 | permission 필요 | permission 필요 | P + permission | P + permission | P + permission | - | - |
| 업무분류 관리 | permission 필요 | permission 필요 | permission 필요 | permission 필요 | - | - | - |
| 전체 직원·구성원 목록 | A 또는 permission | A 또는 permission | 별도 직원조회 permission | 별도 직원조회 permission | 별도 직원조회 permission | 별도 직원조회 permission | - |
| 직원·인력 프로필 관리 | A 또는 permission | A 또는 permission | 별도 직원관리 permission | 별도 직원관리 permission | 별도 직원관리 permission | - | - |
| 내 정보 조회 | 본인 | 본인 | 본인 | 본인 | 본인 | 본인 | 본인 |
| 보고서 조회·내보내기 | A 또는 permission | A 또는 permission | P + permission | P + permission | P + permission | P/R | - |

매트릭스 해석 원칙:

- 역할명은 권한 묶음의 기본값이며 최종 검사는 permission으로 수행한다.
- 전체 프로젝트 접근은 `tenant_admin`과 `manager`만 가지며, 위험한 write 동작은 이 역할에도 별도 permission을 요구할 수 있다.
- `project_admin`은 전체 프로젝트에서, `project_coordinator`는 지정 프로젝트에서 운영 permission을 행사한다.
- `view_only`는 상태를 바꾸는 요청을 허용하지 않는다.
- `guest`는 `view_only`보다 좁은 정보와 기능만 허용한다.
- 지도 객체, 시설물, 파일, 업무 이벤트와 보고서를 포함한 하위 객체는 상위 프로젝트 접근권한을 상속한다.
- 프로젝트 참여자 제한 조회와 전체 직원·구성원 조회는 서로 다른 permission과 response schema를 사용한다.
- tenant 역할이나 project membership이 비활성화되면 즉시 접근에서 제외한다.

## 11. 개발 Phase

### Phase 0. 설계 고정과 안전 기준

- 이 문서를 제품 구조 기준으로 승인
- 역할 코드와 permission codename 목록 확정
- 중앙 user와 employee 연결 lifecycle 확정
- 프로젝트 접근 test matrix 확정
- migration·rollout·rollback 원칙 수립

### Phase 1. 중앙 계정·가입·권한 안정화

- 중앙 계정 상태와 승인 흐름 정리
- 선택적 초대코드와 승인 근거 추적
- 그룹 가입·역할 요청 흐름 완성
- 중앙 사용자 상세의 소속·역할 관리 안정화
- 권한 변경 감사와 session/cache 무효화
- employee 계정 연결 요청과 승인 흐름 설계

완료 기준: 승인된 사용자만 로그인하고, 승인된 tenant와 역할만 획득하며, 역할 변경이 서버 권한에 즉시 반영된다.

### Phase 2. 프로젝트 접근 기반 구축

- 프로젝트 membership schema와 service 설계
- 역할별 전체/지정 프로젝트 query 정책 구현
- 목록·상세·JSON·write path에 공통 검사 적용
- 이벤트·파일·지도·보고서의 상위 프로젝트 검사 적용
- deny-by-default DB-free 및 integration test 추가

완료 기준: `tenant_admin`, `manager`, `project_admin`, `project_coordinator`는 전체 프로젝트를 조회한다. `project_admin`은 전체 프로젝트를 운영하고 `project_coordinator`, `worker`, `view_only`, `guest`는 지정 프로젝트만 운영하거나 접근한다. 직접 URL과 모든 하위 객체 접근도 같은 결과를 낸다.

### Phase 3. 테넌트 정보 구조와 메뉴 정리

- 테넌트 메뉴와 permission 연결
- 프로젝트 참여자 UI
- 직원·인력과 중앙 계정 연결 상태 UI
- 내 정보와 내 권한 화면
- 계약·협력사·프로젝트 메뉴 경계 정리

### Phase 4. 업무분류와 이벤트 정리

- tenant 업무분류 모델과 관리 UI
- 이벤트와 업무분류 연결
- 중앙 카탈로그 선택적 매핑 설계
- 과거 이벤트 보존·비활성화 정책
- 프로젝트 접근권한 상속 검증

### Phase 5. 파일·지도·보고서 확장

- 프로젝트 기반 첨부와 다운로드 정책 확대
- 현장사진·시설물·지도 객체 연결
- 보고서와 내보내기 권한
- 대용량·감사·보존 정책

## 12. 아직 보류할 항목

- tenant별 중앙 카탈로그 별칭·확장·숨김의 전체 기능
- 중앙 카탈로그와 업무분류의 자동 매핑
- 복수 role을 한 user-group에 동시에 부여하는 구조
- 프로젝트별 세부 역할을 tenant role과 별도로 운영할지 여부
- guest가 볼 수 있는 필드 단위 제한의 상세안
- tenant 메뉴 자체를 관리자가 자유롭게 커스터마이징하는 기능
- 자동승인 정책
- 초대 링크 자동 로그인 또는 자동 tenant 연결
- 고급 지도 분석과 공간별 세부 권한
- 자동 보고서 생성과 복잡한 통계
- 대량 cross-tenant 운영 기능

보류 항목은 현재 기본 권한 경계를 약화시키지 않는 방식으로만 향후 검토한다.

## 13. DB 변경 가능성이 있는 항목

아래 항목은 설계 후보이며 이 문서만으로 migration 실행을 승인하지 않는다.

| 영역 | 변경 가능성 |
|---|---|
| 중앙 계정 승인 | 명시적 account status, 승인자·승인일 metadata 보강 가능 |
| 초대코드 | 중앙 invitation code와 사용·검증 이력 table 필요 가능 |
| 역할 요청 | 계정·그룹·요청 역할·결정 이력을 담는 구조 보강 가능 |
| employee 연결 | `central_user_id`의 index, uniqueness 또는 link audit table 필요 가능 |
| 프로젝트 접근 | tenant DB에 project membership table 필요 가능 |
| project member 권한 | active 상태, 배정자, 기간, project role 또는 override permission 필요 가능 |
| 업무분류 | tenant work category hierarchy table 필요 가능 |
| 이벤트 연결 | event에 tenant work category reference 필요 가능 |
| 카탈로그 매핑 | tenant category와 central catalog 간 mapping table 필요 가능 |
| 감사 | 계정·승인·권한·membership 변경 audit table 필요 가능 |

cross-database FK는 사용하지 않는다. 중앙 user UUID를 tenant metadata에 저장할 경우 무결성 점검, 재시도, orphan 처리, 삭제·비활성 정책을 application level에서 설계한다.

## 14. Codex 개발 이슈로 분리할 때의 원칙

각 Codex 이슈는 하나의 검증 가능한 목표만 가져야 한다.

### 14.1 필수 이슈 구성

- 기준 branch와 commit
- 허용 파일과 금지 파일
- 현재 동작과 원하는 동작
- 중앙 DB와 tenant DB 중 어느 범위인지
- read-only인지 write인지
- permission과 project scope 규칙
- migration 필요 여부
- DB-free test와 integration test 범위
- 실패 시 stop condition
- 민감정보 출력 금지 항목
- 검증 명령과 작업 후 보고 형식

### 14.2 권장 분리 순서

1. read-only current-state analysis
2. schema and migration design
3. DB-free authorization service implementation
4. migration static review
5. migration precheck와 backup readiness
6. 별도 승인된 migration execution
7. query·view·template 연결
8. 회귀 및 권한 우회 테스트
9. 수동 browser smoke 결과 문서화

### 14.3 한 이슈에 섞지 않을 작업

- 중앙 계정 변경과 tenant employee 변경
- 프로젝트 membership schema와 전체 UI 개발
- 권한 로직 변경과 광범위한 메뉴 개편
- migration 실행과 browser smoke
- catalog 확장과 업무 이벤트 CRUD
- 여러 tenant에 대한 일괄 migration 또는 metadata repair

### 14.4 테스트 원칙

- 허용 역할 성공 테스트와 금지 역할 403 테스트를 함께 둔다.
- project_coordinator의 미배정 프로젝트 쓰기와 worker·view_only·guest의 미배정 프로젝트 접근을 차단한다.
- URL 직접 접근, JSON/API, 첨부, 이벤트 등 우회 경로를 검증한다.
- 다른 tenant ID나 project ID를 payload로 바꾸는 공격을 검증한다.
- inactive membership, inactive role, inactive project의 fail-closed 동작을 검증한다.
- 역할 변경 후 session 또는 permission cache가 오래 남지 않는지 검증한다.

## 15. v1 결론

GeoFlow v1의 인증·권한 주체는 중앙 `users.id`다. tenant `employee_profile`은 접속자가 아니라 직원·인력 데이터이며, 필요할 때만 중앙 계정과 연결한다. 테넌트 권한은 중앙 `user_group_map`의 role과 permission에서 계산한다. `tenant_admin`, `manager`, `project_admin`, `project_coordinator`는 tenant 전체 프로젝트를 조회하며, `project_admin`은 전체 운영, `project_coordinator`는 활성 membership 프로젝트 운영 권한을 가진다. `worker`, `view_only`, `guest`는 활성 membership으로 지정된 프로젝트만 접근한다. 지도 객체, 시설물, 파일, 업무 이벤트와 보고서도 이 project scope를 그대로 상속한다.

전체 직원·구성원 목록과 직원 프로필 관리는 tenant 관리자·manager 또는 별도 직원관리 permission의 영역이다. 프로젝트 역할만 가진 사용자는 내 정보만 볼 수 있으며, 지정 프로젝트 안에서 필요한 제한 필드의 참여자 목록만 조회한다. 직원 데이터 자체는 어떤 경우에도 로그인·권한 원장이 되지 않는다.

중앙 카탈로그는 공통 표준이고 tenant 업무분류와 이벤트는 운영 데이터다. 둘은 필요할 때 명시적으로 매핑한다. 초대코드는 선택적 추적 근거이며 자동승인의 근거가 아니다. 이후 개발은 이 경계를 유지하면서 계정·권한, 프로젝트 접근, tenant 메뉴, 업무분류·이벤트 순으로 작은 이슈와 검증 가능한 단계로 진행한다.
