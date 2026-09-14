# 업무폼 실행 가드 및 보호된 코드 배포

이 변경은 후보 `73ea836805a63268a99c209e6036c4b8d7fa45c8`에 실행 가드만 보완한다. 기존 72문/67행 업무 계획과 설치 플러그인은 그대로다. 게시할 최종 SHA는 검토 패키지 manifest에 기록한다. 원격 release는 이번 확인 시 `d34904e8eac35d062c8687e9e9807c6a035abdb2`였다.

## 실제 원본 대조 상태

사용자는 실제 pgAdmin Messages에 31개 삭제 필드명/UUID가 있고 sys_chk는 wtl_pipe_lm/wtl_valv_ps에 있다고 확정했다. 후자는 정책/검사에 반영했다. 다만 이번 세션에 노출된 첨부 경로의 세 pasted-text 파일과 워크스페이스에는 Messages 원본이 없었다. 따라서 **운영 31개 ID의 대조 완료 또는 운영 승인 파일 생성 완료라고 보고하지 않는다.** 기존 합성 fixture ID를 복사하지 않았다. 다시 pgAdmin을 조회할 필요는 없으며 기존 원본 파일이 접근 가능해지면 아래 오프라인 대조를 수행한다.

`business_messages.verify_messages()`는 전체 조회 완료·DB·프로젝트·선택 profile, feature ID, 기존 변경 대상 field ID 51개(기존 정의/reference 20 + 비활성화 대상 31), 출력된 type/group/widget 및 모든 profile 설정을 비교한다. 31개의 실제 테이블/필드명/field UUID 목록을 결과에 기록하고 sys_chk의 두 테이블도 검사한다. 동일 건수의 다른 UUID·권한·불완전 원본은 거부한다. Messages에 없는 label/standard_name/profile_field 행 UUID는 실제 읽기 전용 승인 snapshot에 별도로 고정하고 승인자가 검토한다.

## 적용 범위 강제

운영 CLI `scripts/ops/reconcile_gis_business_fields.py --apply`는 이제 다음을 필수로 요구한다.

- 원본 Messages 대조가 완료된 승인 파일 `--approval-file`
- 그 파일을 독립 검토하여 고정한 SHA256 `--approval-sha256`
- 기존 백업 디렉터리 정책과 정식 tenant resolver/운영 역할

실행 시 자동으로 현재 DB를 승인 상태로 간주하지 않는다. 승인 파일 export와 apply를 한 번에 실행할 수도 없다. 운영 파일에 raw Messages 검증 evidence가 없으면 DB 연결 전에 거부한다. 해시가 틀리면 연결 전에 거부한다.

잠금은 기존 advisory lock과 metadata/profile/reference 테이블 잠금, 대상 5개 시설물 잠금을 재사용한다. feature ID가 가리키는 논리 대상도 고정하기 위해 meta_feature_type 잠금을 추가하고 프로젝트 식별 행에 FOR SHARE를 사용한다. 잠금 후 before snapshot과 계획을 다시 생성한다.

1. 데이터베이스·프로젝트 코드/UUID·group/alias 승인 context 및 물리 schema/기본값/제약/trigger/reference/profile 공유 조건이 같아야 한다.
2. 기존 feature/field/profile 및 profile_field ID, 변경 전 값, 다른 profile 설정까지 승인 before image와 비교한다. 업데이트하지 않는 기존 field 속성도 drift를 검사한다.
3. 실행 SQL은 원래 planner의 정확한 **다섯 DML template**만 허용한다. 대상은 gis.meta_field_def/gis.profile_field다. ALTER/CREATE/DROP/DELETE, 시설물·reference 값 DML, 다른 컬럼/SQL 문법은 whitelist에 없다.
4. 허용 SQL을 해석하여 생성한 논리 변경과 전체 after image가 승인 파일과 일치해야 한다. 72문·67행이 같아도 대상 ID·변경 컬럼·값이 다르면 첫 DML 전에 중단한다.
5. 신규 field UUID는 feature ID/physical_name, 신규 profile 연결 UUID는 profile ID/논리 field 조합으로 정규화한다. 기존 행의 UUID 변경은 허용하지 않는다.
6. 정확한 승인 after image이고 planner도 0건이면 잠금 확인 후 0건으로 종료한다. 기존 dry-run의 0건을 신뢰하지 않는다. 잠금 전후 상태가 바뀌어 새 변경이 필요해진 경우 백업 없는 no-op 경로에서 쓰지 않고 중단한다.
7. 부분 적용·다른 0건 상태·권한 drift는 자동 보완하지 않는다. 쓰기마다 영향 행 1개를 확인하고, 적용 후 전체 after image·불변 조건·계획 0건을 다시 검증한다. 실패 시 운영 CLI가 rollback한다.

### 승인 파일 준비와 사용

원본/승인 파일 경로는 운영 기록으로 확정한 파일을 사용한다. 비밀값은 파일/명령에 넣지 않는다. 원본이 현재 제공되지 않아 아래 변수의 파일을 임의 생성하지 않았다.

```sh
# 기존 정식 역할, 서버 저장소 루트/서비스 환경. 읽기 전용 후보 생성만 수행.
PYTHONPATH=. "$SERVICE_PYTHON" scripts/ops/reconcile_gis_business_fields.py \
  --group-code cheonan --db-alias cheonan_db \
  --project-id 86f52715-3cca-4124-9cc6-cb7c6a7e9c4e \
  --messages-file "$MESSAGES_FILE" --export-approval "$APPROVAL_FILE"

# 별도 오프라인 재대조도 가능. 운영 DB/Secrets Manager 접근 없음.
PYTHONPATH=. "$SERVICE_PYTHON" scripts/ops/verify_business_messages.py \
  --messages "$MESSAGES_FILE" --approval "$APPROVAL_FILE" --output "$ID_MATCH_REPORT"

# 파일 전체 before/after/실제 ID를 검토한 승인 SHA를 사용한다.
# 실행하면서 현재 파일 해시를 자동 계산하여 '승인'으로 대신하지 않는다.
PYTHONPATH=. "$SERVICE_PYTHON" scripts/ops/reconcile_gis_business_fields.py \
  --group-code cheonan --db-alias cheonan_db \
  --project-id 86f52715-3cca-4124-9cc6-cb7c6a7e9c4e \
  --apply --backup-dir "$APPROVED_BACKUP_DIR" \
  --approval-file "$APPROVAL_FILE" --approval-sha256 "$APPROVED_SHA256"
```

이것은 운영 실행 지시가 아니다. 원본 대조/승인 해시/운영 유지보수 승인이 준비된 이후의 기존 정식 역할용 명령이다. 763개 공유 프로젝트와 다른 profile에 대한 영향은 이전 metadata 한정 계획과 같다. 실제 backup·운영 역할·운영 연동 검증을 격리 테스트로 대신하지 않는다.

## 보호된 배포 경로

새 `gis-business-contract-code-deploy.yml`은 **workflow_dispatch만** 지원하고 기존 `production` Environment, contents:read, 동일 SSH secrets·StrictHostKeyChecking, release branch/HEAD 확인, 깨끗한 운영 checkout, 서비스 health 확인, 실패 시 코드 복구 절차를 그대로 재사용한다. 수동 SSH 명령을 운영 실행 경로로 제공하지 않는다.

입력 `approved_sha`는 검토·병합된 release의 정확한 SHA여야 한다. Actions의 GITHUB_SHA 및 최신 원격 release HEAD와 다르면 배포하지 않는다. 실제 이전 운영 SHA와 후보 사이의 변경 파일도 이 업무의 명시적 allowlist를 벗어나면 중단한다. 다른 release 변경을 따라가며 범위를 자동 확대하지 않는다.

기존 일반 배포 workflow는 그대로 보존한다. 새 경로에는 **tenant migration, reconcile/DB 적용, pip install, collectstatic이 없다.** 기존 dependency 상태의 pip check와 DB 연결을 read-only로 제한한 Django check, 코드 checkout·서비스 재시작·healthcheck·필요 시 코드 rollback만 수행한다. DB metadata 적용은 별도의 승인된 정식 역할 단계다. 서버 재시작/공통 GIS 검증 코드의 영향은 서비스 전체이므로 metadata의 5개 시설물 범위로 축소하여 설명하지 않는다.

이 workflow는 아직 게시/등록/실행되지 않은 로컬 변경이다. 기존 production Environment를 참조하며 GitHub 관리 설정/보호 규칙을 변경하지 않는다. 실제 Environment 승인자는 기존 규칙에 따라 승인해야 한다. 이 세션에서 해당 관리 설정을 다시 읽거나 승인 상태를 만들어 낸 것은 아니다.

## 관련 검사와 다음 승인 범위

- 격리 PostgreSQL 검사 16개 통과: 72문 적용·정확한 재실행 0건, 같은 수의 다른 대상/값/ID/권한 거부, 부분 적용 거부, 금지 SQL 거부, after image 실패 rollback, Messages ID 대조·불완전/다른 ID 거부, CLI 필수 승인/원본 인자 강제.
- workflow 검사 3개 통과: YAML 구성·production/정확 SHA/수동 dispatch gate, 부수 mutation 단계 없음·정확 파일 allowlist, 모든 shell 블록 bash -n 검사. 배포 명령은 실행하지 않았다.
- PR용 `GIS business approval guard` CI workflow는 격리 PostgreSQL에서 위 관련 검사만 실행한다. 기존 Release preflight/branch 보호 CI를 대체하지 않는다. GitHub CI 실행 성공은 아직 주장하지 않는다.

승인할 다음 범위는 최종 커밋을 기존 topic branch에 게시 → release/stabilized-deploy 대상 PR → 기존 필수 CI + 새 guard CI → 검토 후 보호된 병합이다. 게시/PR/CI/병합 승인에 DB 적용·Environment 배포 승인·재시작을 포함하지 않는다. 병합 이후 정확한 merge SHA로 새 보호 workflow의 별도 배포 승인을 받고, metadata 적용은 원본 ID 대조와 승인 파일/해시가 완성된 뒤 별도 승인한다.
