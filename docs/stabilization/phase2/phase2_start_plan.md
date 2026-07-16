# Phase 2 Start Plan

## 1. 기준 상태

- 기준 작업 폴더: C:\GeoFlow\geoflow_web_commitA_clean
- 이전 안정화 브랜치: phase1-s3-event-clean
- Phase 1 최종 HEAD: de0fd01 phase1: document archive relocation
- Phase 2 작업 브랜치: phase2-clean-base
- 원본 dirty 보관본: C:\GeoFlow\geoflow_web
- Phase 1 archive: C:\GeoFlow\_phase1_archive

## 2. Phase 1 완료 요약

- S3 Attachment 구조 정리 완료
- ProcessEvent / ProcessEventAttachment 연결 완료
- 계약 상세 이벤트 타임라인 연결 완료
- 직원 상세 사진/PDF 첨부 연결 완료
- migration 0006~0018 chain 정합화 완료
- cheonan_db webgisapp 0001~0018 적용 상태 확인 완료
- 원본 main dirty 상태 분석 완료
- Phase 1 산출물 archive 정리 완료

## 3. Phase 2 기본 원칙

- 기준 작업은 phase2-clean-base 브랜치에서 진행
- 원본 C:\GeoFlow\geoflow_web는 직접 수정하지 않음
- 원본 dirty 변경은 필요한 파일만 선별 검토
- migration은 별도 승인 전까지 실행하지 않음
- makemigrations 금지
- git push 금지
- cheonan_db 구조 변경 금지
- .env 출력 금지

## 4. Phase 2 후보 작업

1. 원본 main original tracked only 44개 / untracked only 56개 선별 검토
2. S3/Event UI 안정화
3. 계약 상세 이벤트 UX 개선
4. 직원 첨부 기능 회귀 테스트
5. 권한/역할 기반 접근 제어 정리
6. WebGIS 화면과 AdminKit 화면 정리
7. Phase 2 테스트 체크리스트 작성

## 5. 우선순위 제안

1순위:
- 원본 main에 남은 변경을 주제별로 분류한다.

2순위:
- clean branch에 이미 반영된 S3/Event 기능은 그대로 유지한다.

3순위:
- 원본 dirty 변경 중 필요한 UI/기능만 새 브랜치에 재구성한다.

## 6. 다음 작업

다음 작업은 원본 dirty 변경 중 clean branch에 없는 파일들을 주제별로 분류하는 것이다.

분석 기준 파일:
- C:\GeoFlow\_phase1_archive\main_dirty_analysis_after_phase1_clean\10_original_tracked_only_files.txt
- C:\GeoFlow\_phase1_archive\main_dirty_analysis_after_phase1_clean\11_original_untracked_only_files.txt

## 7. 금지 사항

- git push 금지
- migrate 금지
- makemigrations 금지
- 원본 main merge 금지
- 원본 main cherry-pick 금지
- 원본 main patch apply 금지
- 원본 main reset/restore/clean 금지
- cheonan_db 구조 변경 금지
- .env 출력 금지
