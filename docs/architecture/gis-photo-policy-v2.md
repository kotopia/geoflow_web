# GIS 사진 카탈로그 v2 계약

중앙 원본은 `photo_policy → photo_policy_template → photo_template → photo_variant → photo_slot`이다.
정책은 L2/L3와 Layer를 매칭하고 여러 Template을 순서대로 연결한다. 첫 활성 Template과
그 안의 첫 활성 Variant가 최초 fallback이며 DIRECT/INDIRECT/GENERAL 전역 enum은 없다.

`GET /gis/projects/{project_id}/api/photo-policies/`의 각 layer policy는 다음을 반환한다.

```json
{"policy_id":"…","layer_id":"…","templates":[
  {"id":"…","name":"노출관로측량","sort_order":0,"variants":[
    {"id":"…","code":"DIRECT","name":"직접","sort_order":0,"slots":[]}
  ]}
]}
```

QGIS 최근 선택은 사용자 profile의 QSettings에 `project_id/layer_id/template_id/variant_id`로
저장한다. 현재 payload에 없는 ID는 사용하지 않고 ordered fallback으로 되돌린다. 객체
`ext_data.photo.capture_mode`는 더 이상 읽거나 쓰지 않는다. QField도 후속 구현에서 같은
validation/fallback 규칙을 사용하되 이번 변경에는 QField UI가 포함되지 않는다.

정형 사진은 tenant `gis.feature_photo.template_id/variant_id/slot_id` 세 값을 모두 저장한다.
추가사진은 세 값을 모두 NULL로 두며 `title`, `note`를 사용할 수 있다. S3 namespace,
500KB 정규화, EXIF, 편집본, annotation JSON, pending-save 및 soft delete 계약은 유지한다.

중앙 전환 SQL은 서비스 전 기존 사진 카탈로그 테스트 정의만 초기화한다. Tenant 기존 사진과
S3 객체는 자동 삭제하지 않는다. 운영 적용은 읽기 전용 inventory와 별도 보호 승인이 필요하다.
