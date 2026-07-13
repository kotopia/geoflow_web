# Phase 1 Migration 0015-0018 Review

## 1. 전체 판단

- 파괴적 DDL 여부: 0015~0018 자체에는 파괴적 DDL 없음
- cheonan_db 기존 데이터 손상 위험: 직접 삭제/갱신은 없어 낮음
- 신규 스키마/테이블/컬럼 생성 여부: 있음
- 즉시 migrate 가능 여부: 조건부 가능하지만 현재는 실행 금지
- 별도 승인 필요 여부: 필요
- 핵심 위험: 객체 선존재, 부분 적용, app label 기록 혼선, 롤백 시 데이터 손실

## 2. 파일별 검토

### 0015_attachment.py

Operations:
- CreateModel Attachment

생성/변경 객체:
- ops.attachments
- id, entity_type, entity_id, purpose, object_key, original_name, mime_type, size_bytes, sha256, active, ord, meta, created_at, updated_at
- object_key unique
- idx_att_entity
- idx_att_entity_purpose_ord

위험 DDL:
- 없음
- DROP/RemoveField/DeleteModel/RunSQL DROP 없음

판단:
- 비파괴 생성형 DDL
- 단, ops.attachments가 이미 있으면 relation already exists로 실패 가능

### 0016_add_attachment_soft_delete.py

Operations:
- AddField deleted_at
- AddField deleted_by
- AddField is_deleted

생성/변경 객체:
- ops.attachments.deleted_at
- ops.attachments.deleted_by
- ops.attachments.is_deleted

위험 DDL:
- 없음

판단:
- 비파괴 컬럼 추가
- 동일 컬럼 선존재 시 duplicate column 오류 가능

### 0017_attachment_kind_attachment_parent.py

Operations:
- AddField kind
- AddField parent

생성/변경 객체:
- ops.attachments.kind
- ops.attachments.parent_id
- self FK parent_id -> ops.attachments.id
- FK 인덱스 생성 가능

위험 DDL:
- 없음

판단:
- 비파괴 확장
- 선행 attachments 테이블/컬럼 상태 불일치 시 실패 가능

### 0018_processevent_processeventattachment.py

Operations:
- CreateModel ProcessEvent
- CreateModel ProcessEventAttachment

생성/변경 객체:
- ops.process_events
- ops.process_event_attachments
- idx_event_scope
- idx_event_scope_stage
- idx_event_status
- idx_event_att_ord
- unique_event_attachment
- attachment_id FK
- event_id FK

위험 DDL:
- 없음

판단:
- 비파괴 생성형 DDL
- 동일 테이블 선존재 시 relation already exists로 실패 가능

## 3. dependencies 검토

- 0015 -> 0014
- 0016 -> 0015
- 0017 -> 0016
- 0018 -> 0017

주의:
- 0014_add_employee_profile_address_fields.py에 RunSQL 존재
- 0014 미적용 DB에서는 0015~0018 적용 전 0014가 선행 실행될 수 있음
- 0011~0013 경로의 ops.schema_version 및 ops.schema_version_bump 상태도 확인 필요

## 4. app label / django_migrations 주의

- geoflow_ops 앱 label은 apps.py에서 webgisapp으로 고정
- migration dependency도 webgisapp 기준
- django_migrations에는 app=webgisapp, name=0015~0018로 기록됨
- 과거 app=geoflow_ops 기록이 섞여 있으면 적용 판단 혼선 가능
- 중복 실행 또는 미적용 오판 위험 있음

## 5. models.py와 migration 정합성

Attachment:
- 0015 + 0016 + 0017 최종 상태와 정합

ProcessEvent:
- 0018 정의와 정합

ProcessEventAttachment:
- 0018 정의, UniqueConstraint, index, FK와 정합

불일치 가능성:
- 코드-마이그레이션 불일치보다는 DB 선상태 불일치가 주요 리스크

## 6. cheonan_db 적용 리스크

기존 테이블 충돌 가능성:
- ops.attachments
- ops.process_events
- ops.process_event_attachments

이미 수동 생성된 테이블 가능성:
- grant_cheonan_db_geoflow_local.sql에 ops.attachments 소유권 변경 주석 흔적 존재

migrate 실패 가능성:
- relation already exists
- duplicate column
- FK 오류
- schema 권한 문제
- 선행 migration 상태 불일치
- django_migrations app label 기록 혼선

데이터 손상 가능성:
- 전진 적용 자체는 낮음
- 롤백 시 데이터 손실 위험 큼

## 7. 롤백/복구 주의

- 0018 롤백 시 ops.process_events, ops.process_event_attachments 삭제 가능
- 0017 롤백 시 kind, parent_id 데이터 손실 가능
- 0016 롤백 시 soft delete 이력 컬럼 데이터 손실 가능
- 0015 롤백 시 attachments 메타데이터 전량 손실 가능

## 8. 적용 전 필수 확인 SQL

아래 SQL은 문서에 기록만 하고 실행하지 않습니다.

```sql
SELECT app, name
FROM django_migrations
WHERE app = 'webgisapp'
  AND name IN (
    '0014_add_employee_profile_address_fields',
    '0015_attachment',
    '0016_add_attachment_soft_delete',
    '0017_attachment_kind_attachment_parent',
    '0018_processevent_processeventattachment'
  )
ORDER BY name;

SELECT
  to_regclass('ops.attachments'),
  to_regclass('ops.process_events'),
  to_regclass('ops.process_event_attachments');

SELECT column_name
FROM information_schema.columns
WHERE table_schema = 'ops'
  AND table_name = 'attachments'
  AND column_name IN ('deleted_at', 'deleted_by', 'is_deleted', 'kind', 'parent_id');

SELECT * FROM ops.schema_version;
```