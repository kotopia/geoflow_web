# Main Dirty Analysis After Phase 1 Clean

## 1. 분석 대상

- 원본 작업 폴더: C:\GeoFlow\geoflow_web
- 원본 브랜치: main
- 원본 main HEAD: 502a73c phase1: document commit A temp diff review
- clean 작업 폴더: C:\GeoFlow\geoflow_web_commitA_clean
- clean 브랜치: phase1-s3-event-clean
- clean HEAD: fbf1447 phase1: update s3 event clean branch result

## 2. 백업 상태

원본 main dirty 상태는 아래 위치에 백업됨.

- C:\GeoFlow\_phase1_archive\main_dirty_backup_before_clean_branch_merge
- C:\GeoFlow\_phase1_archive\main_dirty_backup_before_clean_branch_merge\main_tracked_changes.diff
- C:\GeoFlow\_phase1_archive\main_dirty_backup_before_clean_branch_merge\main_untracked_files.txt
- C:\GeoFlow\_phase1_archive\main_dirty_backup_before_clean_branch_merge\full_worktree_copy

전체 worktree 복사 결과:
- robocopy exit code: 1
- copied file count: 6011
- git status count at backup time: 103

## 3. 분석 파일

분석 결과 파일 위치:
- C:\GeoFlow\_phase1_archive\main_dirty_analysis_after_phase1_clean

생성 파일:
- 01_status_short.txt
- 02_diff_stat.txt
- 03_tracked_name_status.txt
- 04_untracked_files.txt
- 05_clean_branch_changed_files.txt
- 06_original_tracked_changed_files.txt
- 07_overlap_clean_vs_original_tracked.txt
- 08_overlap_clean_vs_original_untracked.txt
- 09_clean_only_files.txt
- 10_original_tracked_only_files.txt
- 11_original_untracked_only_files.txt

## 4. 수량 요약

- 원본 main status 항목: 103개
- 원본 tracked 변경 파일: 51개
- 원본 untracked 파일: 70개
- clean branch 변경 파일: 22개

## 5. clean branch와 원본 tracked 변경 겹침

겹치는 tracked 파일 수: 7개

파일:
- control/context_processors.py
- geoflow_ops/models.py
- geoflow_ops/templates/geoflow_ops/contracts/contract_detail.html
- geoflow_ops/templates/geoflow_ops/employees/employee_detail.html
- geoflow_ops/urls.py
- geoflow_ops/views_contracts.py
- geoflow_ops/views_employees.py

판단:
- S3/Event/Attachment 핵심 구현 파일이 원본 dirty 변경과 직접 겹침
- 원본 main에 clean branch를 단순 apply/merge/cherry-pick하면 충돌 또는 기능 회귀 가능성이 높음

## 6. clean branch와 원본 untracked 변경 겹침

겹치는 untracked 파일 수: 14개

파일:
- geoflow_ops/context_processors.py
- geoflow_ops/migrations/0006_create_ops_my_org_units_if_missing.py
- geoflow_ops/migrations/0007_create_ctr_prj_core_tables_if_missing.py
- geoflow_ops/migrations/0008_create_hr_tables_if_missing.py
- geoflow_ops/migrations/0009_create_prj_scope_item_if_missing.py
- geoflow_ops/migrations/0010_tenant_schema_maintenance_citext_cleanup.py
- geoflow_ops/migrations/0011_create_ops_schema_version_if_missing.py
- geoflow_ops/migrations/0012_add_ops_schema_version_bump_function.py
- geoflow_ops/migrations/0013_add_ops_schema_version_bump_alias.py
- geoflow_ops/migrations/0014_add_employee_profile_address_fields.py
- geoflow_ops/migrations/0015_attachment.py
- geoflow_ops/migrations/0016_add_attachment_soft_delete.py
- geoflow_ops/migrations/0017_attachment_kind_attachment_parent.py
- geoflow_ops/migrations/0018_processevent_processeventattachment.py

판단:
- clean branch가 이미 필요한 context processor와 migration chain을 정리해서 commit 완료함
- 원본 main의 같은 파일들은 untracked 상태이므로 원본 main 기준 정리는 위험함

## 7. clean branch에만 있는 파일

파일 수: 1개

파일:
- docs/stabilization/phase1/s3_event_clean_branch_result.md

판단:
- clean branch 결과 문서이며 원본 main에는 없음

## 8. 원본 main에만 남은 변경

- original tracked only: 44개
- original untracked only: 56개

판단:
- S3/Event clean branch 범위를 넘어서는 별도 작업물이 혼재되어 있음
- 중앙관리, 권한, 조직, UI, 정적파일, 서비스 파일 등 여러 주제가 섞여 있을 가능성이 높음
- 현재 단계에서 원본 main 전체를 살리거나 버리는 결정을 하면 위험함

## 9. 최종 판단

원본 main은 현재 병합 대상이 아니라 보관/분석 대상이다.

권장 기준:
- 앞으로의 기준 작업 폴더: C:\GeoFlow\geoflow_web_commitA_clean
- 기준 브랜치: phase1-s3-event-clean
- 원본 main: 백업 완료된 dirty 보관본

## 10. 금지 사항

- 원본 main merge 금지
- 원본 main cherry-pick 금지
- 원본 main patch apply 금지
- 원본 main reset/restore/clean 금지
- git push 금지
- migrate 금지
- makemigrations 금지

## 11. 다음 권장 조치

1. 이 문서를 clean branch에 commit
2. clean branch를 Phase 1 기준본으로 유지
3. 원본 main의 original tracked only 44개와 untracked only 56개는 추후 주제별로 선별 검토
4. 다음 개발은 clean branch에서 진행
5. cheonan_db는 webgisapp 0001~0018 적용 완료 상태이므로 현재 migrate 불필요
