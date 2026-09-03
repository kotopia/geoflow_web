# GeoFlow Finance 문서

이 디렉터리는 GeoFlow Finance의 설계 원칙, 구현 상태, 의사결정, 실패 사례와 운영 배포 이력을 한 곳에서 추적하기 위한 문서 집합이다.

## 문서

- [`finance-architecture.md`](./finance-architecture.md)
  - Finance의 현재 구조와 데이터 원본 원칙
  - 계약/프로젝트/거래처/귀속회사 연결 규칙
  - 청구·세금계산서·지급·입출금·계좌·카드·증빙·삭제함 구조
  - Excel import, 설정값, 권한, soft delete 원칙
  - 2026-09-03 확정한 계약/프로젝트 타임라인 통합 방향

- [`finance-development-history.md`](./finance-development-history.md)
  - Finance Phase 1부터 현재까지의 개발 순서
  - 주요 PR과 migration
  - local/production에서 발생한 실패와 원인
  - 재발 방지 원칙과 운영 배포 결과

## 문서 유지 원칙

1. Finance의 업무 규칙이 바뀌면 코드와 함께 `finance-architecture.md`의 결정 로그를 갱신한다.
2. 장애, migration drift, import 실패, 배포 실패처럼 향후 반복될 수 있는 사건은 `finance-development-history.md`에 원인과 해결책을 기록한다.
3. PR 설명은 구현 단위의 기록이고, 이 디렉터리의 문서는 여러 PR에 걸친 최종 의사결정의 기준 문서로 사용한다.
4. 구현되지 않은 설계는 반드시 `결정됨 / 미구현` 또는 `검토 중`으로 표시해 현재 동작과 혼동하지 않도록 한다.

## 현재 기준

- 문서 작성 기준일: 2026-09-03
- 기준 브랜치: `release/stabilized-deploy`
- Finance는 재무 데이터의 Source of Truth로 유지한다.
- 계약/프로젝트 타임라인에 동일 Finance 데이터를 중복 저장하지 않는 방향을 원칙으로 한다.
