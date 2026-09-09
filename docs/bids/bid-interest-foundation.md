# GeoFlow 관심 입찰 1차 구조

## 범위

1차 범위는 나라장터 용역 공고 수집, 회사별 관심 조건 관리, 자동 매칭,
목록 조회 및 수동 검토까지다. 낙찰률, 투찰률, 순위, 경쟁업체 및 경쟁패턴
분석은 포함하지 않는다.

## 소유권과 경계

- 모든 공고, 필터, 매칭 및 검토 결과는 선택된 tenant DB의 `bid` 스키마가 소유한다.
- 중앙 DB는 사용자·테넌트 인증과 권한만 담당한다.
- 외부 API 키는 `G2B_API_SERVICE_KEY` 환경변수에서만 읽는다.
- 브라우저, 템플릿, DB 테이블, 로그 및 Git에는 API 키를 저장하지 않는다.
- 입찰은 계약 이전 단계다. 1차 기능은 `ctr.contracts` 또는 `prj.projects`를 생성하거나 수정하지 않는다.

## 설정 모델

`bid.filter_values`는 `region`, `industry`, `agency` 중 하나의 종류를 가진다.
회사가 실제로 사용할 코드·이름·별칭만 등록하고 `active`로 사용 여부를 관리한다.
외부 API의 전체 업종 사전을 tenant 설정으로 복제하지 않는다.

`bid.keyword_rules`는 `include` 또는 `exclude` 키워드를 보관한다. 같은 종류의
활성값은 OR, 서로 다른 종류는 AND이며 제외 키워드가 우선한다. 어떤 종류에도
활성 설정이 없으면 그 종류는 제한하지 않는다. 단, 지역·업종·기관·포함 키워드 중
활성화된 긍정 조건이 하나도 없으면 전체 공고를 관심 공고로 오인하지 않도록 아무
공고도 매칭하지 않는다. 구조화된 지역 또는 업종 정보가
없는 공고는 누락시키지 않고 `needs_review`로 표시한다.

발주기관 소재지와 참가가능지역은 같은 값으로 취급하지 않는다. 지역 필터는
참가가능지역 보조 응답을 우선하고, 기관 필터는 공고기관·수요기관을 사용한다.

## 수집

기본 작업은 `getBidPblancListInfoServc`이며 다음 보조 작업을 같은 기간으로
조회해 공고번호와 공고차수로 결합한다.

- `getBidPblancListInfoServcRegion`
- `getBidPblancListInfoServcLicenseLimit`
- `getBidPblancListInfoServcBasisAmount`

보조 작업 하나가 실패해도 기본 공고는 저장하며 sync run은 `partial`로 기록한다.
기본 작업 실패 시 기존 공고를 삭제하거나 미매칭으로 바꾸지 않는다. 동기화는
공고 원본 JSON과 SHA-256 fingerprint를 보존하고 `(source, bid_notice_no,
bid_notice_ord)`로 멱등 upsert한다. 서로 다른 fingerprint는
`bid.notice_revisions`에 남겨 정정·변경 이력을 잃지 않는다.

관리 명령은 중앙 DB 별칭을 거부하며 명시적인 tenant alias가 필요하다.

```bash
python manage.py sync_g2b_bids --database <tenant-alias> --days 2
```

## 권한

이번 좁은 증분은 기존 계약 전 단계의 권한을 사용한다.

- 조회: `contracts.view`
- 검토 상태 저장: `contracts.create` 또는 `contracts.edit`
- 필터 설정 및 수동 동기화: 위 쓰기 권한과 manager 계열 tenant 역할 모두 필요

입찰 담당자를 계약 담당자와 독립 배정해야 하는 시점에 중앙 권한 카탈로그와
역할 매핑을 함께 변경해 `bids.*` 권한으로 분리한다. 문자열만 먼저 추가해 기존
권한 어휘 계약을 깨지 않는다.

## 마이그레이션과 롤백

`0036_bid_interest_foundation`은 tenant DB 전용이며 운영 반영에는 별도 승인이
필요하다. 기존 업무 테이블을 수정하지 않고 새 `bid` 스키마만 추가한다.
기존 tenant 데이터 보호를 위해 자동 reverse DDL은 제공하지 않는다. 시험 DB에서
되돌릴 때는 스키마를 백업한 후 명시적으로 `DROP SCHEMA bid CASCADE` 할 수 있지만,
운영에서는 별도 승인과 보존 판단 없이 실행하지 않는다.
