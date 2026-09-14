# 업무폼 운영 적용 준비 — 2026-09-14

## 고정 결과물과 운영 확인 상태

기준 서버 SHA는 `d34904e8eac35d062c8687e9e9807c6a035abdb2`, 로컬 브랜치는 `fix/qgis-business-form-contract`이다. 최종 로컬 커밋/패키지 SHA256은 별도 검토 패키지의 `manifest.json`에 기록한다. GitHub 게시·병합·배포·재시작은 실행하지 않았다.

설치 플러그인은 metadata 버전 `1.0.0`을 유지한다. 배포 파일명과 SHA256으로 이번 후보를 구분한다. 설치 폴더에는 Git 이력과 이번 작업 직전 원본이 없으므로 과거 사용자 변경까지 정확히 분리한 before/after diff라고 주장하지 않는다. `plugin-vs-release.patch`는 위 release의 integrations 사본과 설치본 전체의 비교다. 서버 저장소의 integrations 사본은 변경하지 않았다. 플러그인 전체 후보 ZIP과 파일별 해시, 작업 관련 파일 목록을 별도로 보존한다. 패키지에는 로컬 DB, 사용자 설정, 캐시, 비밀값을 포함하지 않는다.

운영 준비에서 실제 실행한 읽기 전용 경로:

1. 기존 `C:\GeoFlow\geoflow_web\.env`의 중앙 연결 설정을 메모리에서 사용했다. 비밀값을 복사·출력하지 않았다.
2. 중앙 `users → user_group_map → groups → group_db_config`를 QGIS의 기존 로그인 설정과 대응했다. 활성 group `cheonan`, DB alias `cheonan_db`를 확인했다.
3. 기존 QGIS4 Snapshot에서 가장 최근 캐시 프로젝트 UUID `86f52715-3cca-4124-9cc6-cb7c6a7e9c4e`, 캐시 코드 `26003`, profile 코드 `GEOFLOW_BASE_V1`을 읽었다. 이는 캐시 근거이며 현재 열린 프로젝트/현재 tenant DB의 존재를 증명하지 않는다. 다른 캐시 프로젝트도 있어 UUID를 운영 확정 대상이라고 단정하지 않는다.
4. 아래 도구를 `--apply` 없이 호출했으나 `GroupDBConfig → 기존 Secrets Manager resolver` 단계에서 `TenantDBCredentialError`, 원인 `AccessDeniedException`으로 종료됐다. tenant DB에는 연결하지 못했다. IAM 변경이나 비밀값 대체 경로 우회는 하지 않았다.

```sh
# 기존 정식 운영 Python/환경에서 실행할 읽기 전용 재검사 명령.
# 프로젝트 UUID는 확인된 캐시 후보이며, 첫 inspection에서 DB 존재/귀속을 검증해야 한다.
PYTHONPATH=. .venv/bin/python scripts/ops/reconcile_gis_business_fields.py \
  --group-code cheonan --db-alias cheonan_db \
  --project-id 86f52715-3cca-4124-9cc6-cb7c6a7e9c4e
```

이 명령의 인자는 실제 로컬 실행 인자와 같다. 운영 호스트의 Python 절대 경로는 아직 확보하지 못했으므로 `.venv/bin/python`은 저장소의 통상 실행 예이며, 실제 서비스 ExecStart의 Python과 일치하는지 먼저 확인한다. 비밀번호를 채팅으로 요청하지 않는다. 정식 운영 호스트의 기존 허용된 역할로 재검사하며 새로운 IAM 권한 추가는 이번 승인 범위에 포함하지 않는다.

**실제 DB 변경 예정 건수, 물리 컬럼/metadata 상태, profile 공유 프로젝트 수, 다른 profile 연결, reference 활성 상태, worker 미해결 수, DB 기본값·제약·trigger 상태는 모두 미확인이다. 0건 또는 격리 fixture의 건수를 운영 수치로 대신하지 않는다.** 사전검사의 `operations`는 실행 SQL문 수이며 변경되는 행 수와 다르다. `plan`의 SQL/바인딩과 `inspection`의 각 연결을 함께 검토해야 한다.

## 최종 계약과 범위

| 항목 | 코드에서 확인한 계약 | 운영 적용 조건 |
|---|---|---|
| 신규 status | 폼의 NULL 상태는 등록된 미완료 label의 code를 제안하고 폼 저장 때 전송한다. 기존 상태는 보존한다. foundation SQL은 sys_chk에 기본값이 없다. | 실제 status 기본값이 있으면 동일 미완료 code여야 한다. 없으면 도형만 생성한 객체의 상태는 NULL일 수 있고 폼 저장으로 미완료가 된다. 일괄 DEFAULT 추가는 하지 않는다. |
| date/worker | 플러그인의 도형 생성은 project_id만 로컬 기본값으로 부여한다. date/worker 제안은 폼에만 있으며 저장해야 기록한다. 서버 신규 컬럼도 nullable·기본값 없이 추가한다. | 운영의 date/worker 기본값·생성 컬럼은 충돌 중단. trigger가 해당 값을 채우는지도 검토해야 한다. 임의 삭제하지 않는다. |
| metadata 적용 전 새 서버 | worker_id를 보내지 않는 기존 요청은 검증이 즉시 반환한다. catalog는 worker 컬럼 존재를 확인해 없는 테이블을 건너뛴다. manifest/필드 검증은 기존 metadata를 따른다. | 기존 hr/central schema와 기존 metadata-물리 컬럼이 이미 정합한 경우의 호환성이다. 현재 운영의 선행 rename/오래된 metadata 오류까지 고쳐 주는 배포는 아니다. 구형 클라이언트가 다른 사람 worker를 새로 지정하던 요청은 이제 의도대로 거부된다. |
| metadata 적용 후 구형 요청 | rename 전 ist_ymd/sys_chk를 포함한 오래된 큐를 자동 번역하지 않는다. | 저장 동결 중 큐를 보존·분류하고 새 계약 전환을 확인한 클라이언트부터 재개한다. |
| 영향 범위 | 물리 DDL은 tenant 내 대상 5개 테이블의 모든 프로젝트에 적용된다. 공통 field definition 수정은 이를 사용하는 모든 profile에 적용된다. profile_field 행 변경은 선택 profile에 한정되지만 그 profile을 공유/기본 사용 중인 다른 프로젝트도 영향을 받는다. | 대상 프로젝트 하나에만 영향이 한정된다고 승인받지 않는다. 사전검사 수치를 근거로 공유 범위를 승인해야 한다. |

대상은 `gis.wtl_etc_ps/wtl_fire_ps/wtl_flow_ps/wtl_pipe_lm/wtl_valv_ps`이다. 승인 참조 매핑은 `geoflow_ops/gis/business_fields.py:REFERENCES` 및 5개 status→`GEOFLOW.WORK_STATUS`다. iqt_cde/jht_cde 코드 등록, cst_cde1 재연결, 전체 seed, 기존 날짜/상태/작업자 데이터 변환, 물리 FK는 포함하지 않는다.

## 유지보수와 정확한 적용 순서

1. 검토 패키지 해시 및 로컬 서버 커밋을 확인한다. 별도 승인 후 topic branch 게시·release 대상 PR·필요 CI·병합을 수행한다. 실제 병합 SHA는 게시 전에는 없으므로 로컬 SHA를 운영 병합 SHA로 대신하지 않는다.
2. 기존 정식 운영 호스트/역할에서 위 읽기 전용 도구와 `qgis-business-fields-readonly.sql`을 실행한다. 정확한 프로젝트 귀속, 공유 profile 영향, 전체 SQL 계획, 기존 기본값·CHECK/FK·trigger, worker 집계를 검토한다. 충돌이 있거나 대상이 다르면 여기서 중단한다.
3. 운영 DB 적용 승인을 **확인한 tenant/project + SQL 계획 + 공유 영향 수치 + 백업 경로 + 유지보수 구간**으로 한정해 받는다. 현재 이 승인은 준비 미완료다.
4. 사용자의 QGIS 폼 입력·편집 버퍼·미전송 큐를 보존하고 자동 전송을 중단한다. 해당 tenant의 대상 5개 테이블에 대한 모든 프로젝트·QGIS/WebGIS/QField/API/구조화 작업 쓰기와 GIS metadata/profile/reference 편집을 동결한다. DB table lock만으로 클라이언트 동결을 대신하지 않는다. 도구는 metadata 테이블 단위 잠금을 사용하므로 다른 시설물의 metadata 편집도 영향받는다. 서버 재시작 구간에는 서비스의 모든 tenant 요청이 짧게 중단된다.
5. 이전 배포 SHA·코드/schema 조합, 사전검사 결과, 보존된 로컬 작업을 기록한다. 읽기 전용 사전검사를 통과한 새 서버 코드를 배포한다. 아래 코드 전용 배포 절차만 사용한다. DB 업무폼 도구가 적용되기 전까지 쓰기 동결을 유지한다.
6. 동일 커밋의 도구를 같은 인자로 재검사한다. 승인된 새 비공개 백업 디렉터리를 지정하여 그때에만 `--apply --backup-dir`를 추가한다. 현재는 승인된 백업 경로와 실제 DB 계획이 없으므로 실행 가능한 apply 명령을 발급하지 않는다. 도구가 7개 테이블 백업 후 잠금·재검사·단일 transaction 적용·operations=0 재확인을 수행한다.
7. 읽기 전용 도구/SQL을 다시 실행하여 계획 0건, 기존 date/status non-NULL 수와 fingerprint, 기본값/nullable/제약, profile 제한, reference·worker 집계를 비교한다. rename으로 제약 표현식의 컬럼명은 바뀌어도 제약 의미는 유지되어야 한다.
8. 최소 연동 시험을 수행하고 새 manifest/Snapshot으로 전환한 클라이언트만 순차 재개한다. 오프라인 클라이언트의 이전 큐가 남아 있으면 해당 클라이언트 재개를 보류한다.

## 코드 전용 배포 명령의 조건

기존 `production-release-deploy.yml`과 `production-release-deploy-v2.yml`은 현재 전체 활성 tenant에 다른 migration을 실행한다. 이번 소규모 배포를 위해 그대로 dispatch하지 않는다. 이번 결과에 배포 workflow 수정도 포함하지 않았다.

아래는 정식 운영 호스트에서 별도 승인 후 사용할 코드 전용 절차다. 확인된 서비스명은 `geoflow-stabilized.service`이다. SSH 접속 대상과 런타임 Python·병합 SHA는 현재 세션에서 확정하지 못했으므로 이를 임의로 채우지 않는다.

```sh
set -eu
: "${APPROVED_RELEASE_SHA:?reviewed merged release SHA required}"
: "${SERVICE_PYTHON:?verified existing service Python required}"
service=geoflow-stabilized.service
repo="$(systemctl show "$service" --property=WorkingDirectory --value)"
test -d "$repo/.git"
test -z "$(git -C "$repo" status --porcelain)"
test "$(git -C "$repo" branch --show-current)" = release/stabilized-deploy
previous_sha="$(git -C "$repo" rev-parse HEAD)"
git -C "$repo" fetch origin refs/heads/release/stabilized-deploy
test "$(git -C "$repo" rev-parse FETCH_HEAD)" = "$APPROVED_RELEASE_SHA"
git -C "$repo" merge --ff-only "$APPROVED_RELEASE_SHA"
# Run inside the existing service environment; do not source or print secrets.
cd "$repo"
"$SERVICE_PYTHON" manage.py check
sudo -n systemctl restart "$service"
systemctl is-active --quiet "$service"
health_code="$(curl -sS -H 'Host: geoflow.co.kr' -o /dev/null -w '%{http_code}' --connect-timeout 5 --max-time 10 http://127.0.0.1:8011/login/)"
case "$health_code" in 2??|3??) ;; *) exit 2 ;; esac
printf 'previous_sha=%s\ncandidate_sha=%s\n' "$previous_sha" "$APPROVED_RELEASE_SHA"
```

의존성·정적 파일 변경은 이 후보에 없으므로 pip install/collectstatic/migrate/seed는 포함하지 않는다. 위 health URL/Host는 기존 `production-release-deploy.yml`의 실제 명령이다. 배포 전에도 같은 점검을 수행한다. 쓰기 동결 확보와 이전 SHA의 안전한 복구를 운영 담당자가 함께 관리해야 하며 위 블록은 자동 복구까지 포함한 배포 시스템을 새로 만든 것이 아니다. 게시 이후 release가 진행되었다면 새로 합쳐질 변경·의존성·검사를 재검토한 후 승인 SHA를 고정한다.

## 백업과 부분 실패 조합

백업은 대상 5개 시설물 + `gis.meta_field_def` + `gis.profile_field` custom archive, `metadata-before.json`, readonly inspection/SQL 결과, 서버 이전 SHA, 플러그인 이전 설치본과 사용자 로컬 작업이다. 7개 테이블 archive만으로 빈 DB의 모든 외부 schema/FK 의존성을 재생성할 수는 없다. 복구 리허설은 기존 schema를 갖춘 별도 DB에서 수행했다.

| 실패 시점 | 유지·복구 조합 |
|---|---|
| 코드 배포 전 | 이전 서버 + 이전 DB 유지. 사전검사/백업 실패는 적용하지 않는다. |
| 새 코드 배포 후, DB 적용 전 또는 transaction 실패 | 새 서버 + 이전 DB는 위 호환 조건에서 가능하지만 쓰기는 계속 동결한다. 건강 상태 실패/선행 schema 불일치 시 DB는 그대로 두고 이전 SHA를 정식 코드 복구 절차로 되돌린 뒤 재시작한다. 새 플러그인 계약 전환을 강행하지 않는다. |
| DB commit 후, 동결 유지·백업 이후 쓰기 없음 | 우선 새 서버 + 새 DB 상태에서 진단한다. DB 복구가 필요하면 별도 복구 DB에서 7개 archive 의존성을 검증하고 승인 후 단일 transaction 복구한다. 그 후 이전 서버 + 복원 DB 조합으로 검증한다. 외부 FK 오류에 CASCADE로 강행하지 않는다. |
| DB commit 후 실제 쓰기 있음 | 새 DB를 백업으로 일괄 덮어쓰지 않는다. 쓰기 재동결·추가 백업 후 별도 DB에서 선택 복구 계획을 만든다. 이전 서버 + 새 DB 조합은 자동 선택하지 않는다. |

## QGIS 보존·전환과 최소 실제 연동 시험

기존 폼 입력/편집 버퍼와 SQLite 큐를 구분하여 보존한다. 파일 쓰기가 멈춘 상태에서 .qgz·manifest·.gpkg 및 -wal/-shm을 함께 보존하거나 SQLite backup API를 사용한다. 설치 플러그인도 이전 전체본으로 별도 백업한다. 사용자 프로젝트를 강제 삭제/다운로드하거나 큐 payload를 자동 이름 변경하지 않는다.

운영 적용·사전검사 통과 후 후보 ZIP으로 설치본을 교체하고 QGIS를 사용자가 안전하게 다시 로드한다. 진단에서 구형 계약/큐를 확인하고 기존 사본을 남긴 채 별도 새 Snapshot으로 전환한다. 이전 idempotency ID를 바뀐 payload에 재사용하지 않는다.

최소 실제 연동 시험은 승인된 시험 객체에 한정한다: (1) current_user linked/unlinked/ambiguous 표시와 제한된 workers, (2) 다섯 폼의 기존 날짜·작업자 보존 및 NULL 제안/저장 전 미반영, (3) 저장 시 status code와 tenant 직원 UUID 전송·project_id attributes 제외, (4) 도형만 생성 시 date/worker NULL, (5) 자동 Changeset 저장·receipt 재시도·다른 클라이언트 delta, (6) 타 tenant/권한 없는 작업자 거부와 미해결 기존 작업자의 무관 속성 수정, (7) 버튼 표시·아이콘 접힘·구형 큐 보존이다. 운영에서 대량 입력이나 직원 연결 데이터 조작으로 시험하지 않는다.

## 승인할 범위와 남은 차단점

현재 검토 가능한 승인은 manifest에 기록된 **서버 로컬 커밋의 게시/PR**와 **해시로 고정한 플러그인 후보 전달** 범위다. DB 적용·배포 승인은 tenant 사전검사를 정식 허용 역할에서 완료하고 실제 계획/공유 영향/프로젝트 귀속/백업 경로/병합 SHA를 연결한 뒤에만 확정할 수 있다. 이번 준비 단계에서 게시·운영 변경은 실행하지 않았다.
