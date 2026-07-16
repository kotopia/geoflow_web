# Phase 1 Commit A Temp Staged Diff Review

## 1. 검토 배경

- v2 patch 6개 중 2개는 일반 check 성공, 4개는 일반 check 실패
- 실패한 4개는 --unidiff-zero 조건에서 check 통과
- 실제 index를 보호하기 위해 GIT_INDEX_FILE을 사용한 임시 index에만 적용 테스트 수행
- 임시 staged diff를 C:\GeoFlow\_phase1_archive\phase1_commitA_temp_staged.diff 로 저장
- 실제 index는 최종 확인 결과 비어 있음

## 2. 임시 index 적용 결과

- 임시 index 적용 파일 수: 6
- 임시 index diff 요약:
  - 6 files changed
  - 693 insertions
  - 18 deletions
- 실제 repo index 적용 여부: 적용 안 함
- 실제 working tree 변경 여부: 없음
- DB/migration 영향: 없음

## 3. 전체 판단

- 실제 Commit A 적용 가능 여부: 불가
- v3 patch 필요 여부: 필요
- 단순 patch 자동 추출 방식은 중단 권장
- 이유:
  - 임시 staged diff가 patch 문법/인코딩 측면에서 불안정
  - UTF-16 저장 문제 발생
  - UTF-8 변환 후에도 corrupt patch 발생
  - 일부 hunk가 파일 내 잘못된 위치에 삽입됨
  - views_contracts.py, views_employees.py, contract_detail.html, employee_detail.html에서 문맥 파손 확인

## 4. 파일별 판단

### models.py

포함 내용:
- Attachment 모델
- ProcessEvent 모델
- ProcessEventAttachment 모델
- soft delete, kind/parent, indexes/constraints

혼입 여부:
- Partner/MyOrgUnit/EmployeeProfile 변경은 섞이지 않음

위치/문맥 문제:
- 대형 단일 삽입 hunk라 재적용 시 충돌 가능성 있음
- 구조 자체는 S3/Event 모델 중심

판단:
- 범위는 대체로 맞지만 단독 적용은 보류
- migration 0015~0018과 연결되어 있으므로 별도 검토 필요

### urls.py

포함 내용:
- views_uploads/views_events import
- uploads/events/modal 라우트

혼입 여부:
- employees delete 라우트는 섞이지 않음

위치/문맥 문제:
- 라우트 블록이 urlpatterns 리스트 종료 뒤에 삽입된 형태로 보임
- 문법상 잘못된 위치

판단:
- 내용은 맞지만 위치가 틀려 사용 불가

### views_contracts.py

포함 내용:
- Attachment import
- attachments 조회 및 context 주입 코드

혼입 여부:
- ContractForm widget attrs, 중복검증, Project 동기화 강화는 섞이지 않음

위치/문맥 문제:
- attachments/context 주입이 contract_detail_page가 아니라 contract_json 시작부에 끼어든 형태
- alias, obj, context 선언 전 사용 가능성이 있어 문맥 파손

판단:
- 잘못된 위치 삽입으로 사용 불가

### views_employees.py

포함 내용:
- Attachment/generate_presigned_get_url import
- photo/doc attachment 조회
- photo_url/doc_attachment context 조각

혼입 여부:
- 주소 컬럼 분기, employees_delete, role whitelist/current role 변경은 직접 섞이지 않음

위치/문맥 문제:
- 파일 끝 return [] 라인 뒤에 import가 붙는 형태로 삽입됨
- context dict 조각도 독립적으로 떠 있어 함수 문맥 불일치

판단:
- 위치가 명백히 잘못되어 사용 불가

### contract_detail.html

포함 내용:
- 타임라인 영역
- eventModalMount
- upload-utils/process-events-ui
- ProcessEventsUI.init
- initAttachmentActions

혼입 여부:
- 이벤트 무관 레이아웃 변경 일부가 함께 포함

위치/문맥 문제:
- eventModalMount div와 process-events-ui script 라인이 JS 함수 중간에 삽입된 형태
- endblock 이후 JS 조각이 분리되어 구조 깨짐

판단:
- hunk 위치 오류와 혼입이 있어 사용 불가

### employee_detail.html

포함 내용:
- photo_url 표시
- 사진 업로드 UI
- PDF 첨부 UI
- upload-utils 및 업로드 스크립트

혼입 여부:
- 직원 삭제 동작 스크립트가 함께 들어감
- 일부 레이아웃 변경 조각 동반

위치/문맥 문제:
- 버튼 태그 파손
- script/endblock 경계 비정상
- script 블록 일부가 템플릿 블록 경계 밖으로 밀림

판단:
- 위치 문제와 혼입이 커서 사용 불가

## 5. whitespace / encoding 판단

- trailing whitespace 경고 다수 발생
- 임시 diff 저장 시 UTF-16 인코딩 문제 발생
- UTF-8 변환 후에도 corrupt patch 발생
- v3 또는 재구성 방식에서는 UTF-8, 줄 끝 공백 제거, block 경계 검증 필요

## 6. 결론

- 현재 임시 staged diff는 실제 Commit A에 사용할 수 없음
- 6개 파일 전부 보류 권장
- 성공 patch 2개만 단독 적용하지 않음
- 실패 patch 또는 --unidiff-zero patch 강제 적용 금지
- patch 자동 추출 방식은 위험하므로 중단 권장

## 7. 다음 권장 전략

1. 현재 patch 기반 Commit A 시도 중단
2. clean 기준에서 S3/Event 연결부를 재구성하는 방식으로 전환
3. 별도 clean worktree 또는 별도 작업 디렉터리에서 최소 변경을 재작성
4. 재작성된 diff를 다시 검토 후 실제 index 적용 여부 판단
5. migration 0015~0018은 계속 별도 보류

## 8. 금지 사항

- git apply --cached 실제 적용
- --unidiff-zero patch 강제 적용
- 성공 patch 2개 단독 적용
- git add .
- 남은 6개 파일 전체 git add
- migration 동시 staging
- migrate/makemigrations
- git push
- git restore/reset/clean
