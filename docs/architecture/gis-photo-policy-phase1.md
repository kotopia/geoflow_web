# GIS 사진 정책 Phase 1 계약 (보관됨)

> 이 문서는 최초 Phase 1 계약의 기록이다. 현재 계약은
> `gis-photo-policy-v2.md`를 따른다.

이 변경은 중앙 사진 Definition과 테넌트 GIS 사진 행을 추가한다. 운영 DB에는
자동 적용하지 않는다. 중앙 SQL(`gis-photo-policy-central.sql`)은 중앙 GIS
Definition이 설치된 뒤 별도 승인된 절차에서만 적용하고, 테넌트 migration
`0039_gis_feature_photo`도 운영에서는 별도 승인 후 적용한다.

## 소유권과 식별자

- Catalog의 L1은 L2 부모에서 계산한다. 정책은 L2 UUID, 선택적 L3 UUID,
  중앙 `definition_layer.id`를 참조한다. L3는 레이어를 추가하지 않는다.
- 동일 레이어에 여러 업무범위가 맞으면 L3 지정 정책이 L2 기본보다 우선한다.
  최고 우선순위 정책이 둘 이상이면 `PHOTO_POLICY_CONFLICT`를 반환한다.
- 객체 `ext_data.photo.capture_mode`는 `DIRECT`, `INDIRECT`, `GENERAL`만 허용한다.
  키가 없으면 해당 정책의 기본값을 사용한다. 기존 객체는 작업 세션 값으로 바꾸지 않는다.
- 중앙 정책/템플릿/슬롯은 중앙 DB에만 존재한다. 실제 `gis.feature_photo`는
  테넌트 DB에 있고 일반 첨부 구조에 행을 만들지 않는다.

## 읽기 계약

- `GET /gis/projects/{project_id}/api/photo-policies/`는 권한 있는 프로젝트의
  레이어별 유효 정책과 별도 `photo_policy_revision`을 반환한다.
- `?layer_id={uuid}&feature_id={uuid}`는 해당 프로젝트 객체의 저장된 촬영방식으로
  템플릿을 다시 계산한다. 프로젝트 소속과 물리 객체 존재를 서버에서 확인한다.
- QGIS manifest에는 `photo_policy_url`, `photo_policy_revision`을 추가한다.
  중앙 사진 스키마가 아직 없다면 두 값은 빈 문자열이고 기존 로딩은 유지된다.
- 중앙 관리자의 `GET/POST /control/central/gis/photo-catalog/api/`는
  정의 조회/추가/수정/비활성화다. 중앙 관리자 권한과 CSRF를 사용한다.
- 운영 배포는 같은 API로 Template → Slot → Policy 생성·수정·재조회·비활성화를
  수행하고 전체 트랜잭션을 rollback하는 `smoke_gis_photo_catalog` 검사를 통과해야 한다.

## 사진 API와 S3

- `GET/POST /gis/projects/{project_id}/api/layers/{layer_id}/features/{feature_id}/photos/`
  와 개별 사진 `PATCH/DELETE .../photos/{photo_id}/`를 사용한다.
- presign은 새 UUID와 전용 S3 key, 15분 유효 PUT URL을 반환한다.
- finalize에서 서버가 S3 HEAD로 크기·Content-Type·암호화를 확인한 후 행을 기록한다.
- 전용 키는 `tenants/{tenant_alias}/gis/{project}/{layer}/{feature}/{photo}.{ext}`다.
- 삭제는 테넌트 행을 soft delete한다. S3 객체는 즉시 파괴하지 않는다.

## 적용 및 되돌리기

중앙 DDL과 테넌트 DDL은 additive다. 기록된 사진이 있을 때 테이블을 DROP하는
reverse migration은 제공하지 않는다. 정책 변경은 별도 revision을 바꾼다.
