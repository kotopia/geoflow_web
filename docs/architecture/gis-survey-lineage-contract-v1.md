# GeoFlow GIS Survey lineage contract v1

Status: **deployed server/tenant contract**. This document describes release
`a58ca17205c79ac41ecdaf0e016e302c5d871bd1`. QGIS Connector and QField UI are
out of scope. A client must not infer capabilities marked unsupported here.

## 1. Ownership and coordinates

- `gis.survey_source`, `gis.survey`, and `gis.survey_link` live in each tenant DB.
- Central `gis.definition_layer.id` is stored logically as `survey_link.layer_id`.
- Facility UUID `id` is retained; facility tables receive no `survey_id` column.
- `raw_x/raw_y/raw_z/raw_crs` preserve source coordinates. `geom` and `raw_geom`
  are Point EPSG:4326.
- The DB stores a private `original_file_key`, never bytes or a presigned URL.
- UUIDs and timestamps are JSON strings. PostgreSQL `numeric` point values are
  serialized by Django as JSON strings; longitude/latitude are JSON numbers.

### CRS responsibility

The deployed import contract does **not** obtain or default a project
`working_crs`. For each point, send either:

1. `longitude` and `latitude`, treated as EPSG:4326; or
2. `raw_x` and `raw_y`, plus `EPSG:n` in point `raw_crs` or source `source_crs`.

Point `raw_crs` overrides source `source_crs`. For TM-only input, the Connector
must obtain/configure the correct EPSG and send it. PostGIS performs the sole
`ST_Transform(...,4326)`; QGIS must not transform the same ordinates again.
Missing/invalid CRS returns HTTP 400 `survey_rejected`. When longitude/latitude
are present they determine geometry even if raw values are also present; the
server does not cross-check the two representations.

## 2. Storage contract

### `gis.survey_source`

| Field | Type | Null | Meaning |
|---|---|---:|---|
| id | uuid PK | no | immutable source version ID |
| project_id | uuid | no | tenant project |
| source_group_id | uuid | no | stable lineage/series ID |
| supersedes_id | uuid FK | yes | prior active source version |
| source_type | varchar(20) | no | `GNSS`, `GPS`, `TOTAL`, `CSV`, `XLSX`, `OTHER` |
| original_file_name | text | no | audit/display name |
| original_file_key | text | yes | private storage reference |
| imported_at/imported_by | timestamptz/uuid | no/yes | server audit |
| source_crs | text | yes | normally `EPSG:n` |
| geoid_model | text | yes | geoid identifier |
| calibration_info | jsonb object | no | calibration metadata |
| version | integer | no | positive group version |
| is_active | boolean | no | one active version per group/project |
| note | text | no | default empty string |

A revision inserts a row, deactivates the prior active version, retains
`source_group_id`, and requires the immediately preceding active row as
`supersedes_id`.

### `gis.survey`

Lineage additions are `source_id uuid NULL`, `source_row_id text NULL`,
`raw_crs text NULL`, `raw_code text NULL`, and `raw_geoid_model text NULL`.
During revision, `(project, source_group_id, source_row_id)` retains the logical
Survey UUID while coordinates and `source_id` advance.

The table has legacy/common `worker_id`, `survey_date`, `surveyed_at`,
`survey_code`, `type`, and `raw_data`. Contract v1 stores `raw_data`, but **does
not map top-level or point-level method, survey_date, surveyed_at, or worker_id
into their dedicated columns**. Preserve unsupported per-row source metadata in
point `raw_data`; do not assume dedicated-field persistence.

### `gis.survey_link`

| Field | Type | Null | Meaning |
|---|---|---:|---|
| id | uuid PK | no | client-generated immutable mapping UUID |
| survey_id | uuid FK | no | Survey point in same project |
| layer_id | uuid | no | central definition-layer UUID |
| target_id | uuid | no | facility UUID |
| match_method | varchar(30) | no | `manual`, `nearest`, `code`, `import`, `gnss` |
| match_distance | numeric(12,3) | yes | non-negative |
| match_confidence | numeric(5,4) | yes | 0..1 |
| confirmed_by/confirmed_at | uuid/timestamptz | yes | audit |
| created_at | timestamptz | no | creation time |
| vertex_index | integer | yes | zero-based LineString vertex; null for point |
| link_role | varchar(20) | no | `POINT`, `VERTEX` |
| link_status | varchar(30) | no | `LINKED`, `MANUALLY_MODIFIED`, `UNLINKED` |
| created_by | uuid | yes | creator |
| updated_at/updated_by | timestamptz/uuid | no/yes | latest audit |

`POINT` requires a Point and null `vertex_index`. `VERTEX` requires a LineString
and an in-range non-negative index on create. One non-unlinked mapping may occupy
`(layer_id,target_id,vertex_index)`. Unlinked history does not block reuse.

There is no stable vertex UUID. The server does not remap links after vertex
insert/delete or split. QGIS must explicitly update/remake mappings after the
feature geometry Changeset succeeds. Reapply rejects out-of-range indexes.

## 3. Endpoints and authorization

All endpoints are session-authenticated, project-scoped, tenant-resolved
fail-closed, and require `maps.view`. POST also requires project GIS write
access. JSON uses `Content-Type: application/json`. Source bodies are limited to
20 MiB; Survey-link Changesets to 5 MiB.

| Purpose | Method and endpoint |
|---|---|
| sources/presign/import | `GET/POST /gis/projects/{project_id}/api/survey-sources/` |
| points | `GET /gis/projects/{project_id}/api/survey-points/` |
| mappings | `GET /gis/projects/{project_id}/api/survey-links/` |
| mapping Changeset | `POST /gis/projects/{project_id}/api/survey-link-changesets/` |
| reapply preview | `POST /gis/projects/{project_id}/api/survey-reapply-preview/` |
| reapply execute | `POST /gis/projects/{project_id}/api/survey-reapply/` |

Only Survey-link list/Changeset also have `/api/qfield/` routes. Source import,
point list, and reapply have no QField route in v1.

## 4. Source presign and import

### Presign

POST the survey-sources endpoint:

```json
{"action":"presign","id":"30000000-0000-4000-8000-000000000002","original_file_name":"survey.csv","mime_type":"text/csv"}
```

`id` is optional (server-generated if omitted), filename defaults to
`source.bin`, and `mime_type` is optional. Exact response envelope:

```json
{
  "ok": true,
  "id": "30000000-0000-4000-8000-000000000002",
  "object_key": "tenants/<tenant>/gis/<project>/survey-sources/<id>/<random>.csv",
  "presigned_url": "<private PUT URL>",
  "headers": {"Content-Type":"text/csv","x-amz-server-side-encryption":"<configured value>"}
}
```

`presigned_url` is the HTTP PUT target and `object_key` is later sent as
`original_file_key`. Expiration is 900 seconds. PUT exact bytes and copy every
returned header. Depending on configuration, `headers` may include KMS key ID
or omit MIME/encryption entries that were not signed.

Required order:

1. POST `action=presign`.
2. PUT bytes with returned headers.
3. POST import JSON with returned `object_key`.
4. Server HEAD-verifies tenant/project prefix, existence, non-zero size, and
   configured encryption, then atomically commits source and points.

The server does **not** parse CSV/XLSX. The import JSON must still contain parsed
`points`; parsing is a Connector/importer responsibility.
`original_file_key` is nullable: an import without an archived source file is
accepted, in which case presign/PUT/HEAD verification is skipped.

### Import/revision

```json
{
  "id": "30000000-0000-4000-8000-000000000002",
  "source_group_id": "30000000-0000-4000-8000-000000000001",
  "supersedes_id": "30000000-0000-4000-8000-000000000000",
  "source_type": "TOTAL",
  "original_file_name": "survey-v2.csv",
  "original_file_key": "tenants/<tenant>/gis/<project>/survey-sources/<id>/<random>.csv",
  "source_crs": "EPSG:5186",
  "geoid_model": "KNGeoid18",
  "calibration_info": {"control_set":"2026-10"},
  "note": "recalibrated",
  "points": [
    {"id":"50000000-0000-4000-8000-000000000001","source_row_id":"P001","raw_x":200000.12,"raw_y":500000.34,"raw_z":12.3,"raw_code":"DEP","raw_data":{"method":"TOTAL","survey_date":"2026-10-01"}},
    {"source_row_id":"P002","longitude":127.123,"latitude":36.456,"raw_z":12.1}
  ]
}
```

For v1, `source_group_id` defaults to `id`. Revisions require group ID and
`supersedes_id`. `source_row_id` is required and unique within the array. Point
`id` is used only for a new logical row; a revision match retains the old UUID.

```json
{"ok":true,"source_id":"30000000-0000-4000-8000-000000000002","source_group_id":"30000000-0000-4000-8000-000000000001","version":2,"created":1,"updated":1,"first_revision":18,"last_revision":19,"current_revision":19}
```

There is no row-level partial success/error array. Any bad row rolls back all.
Import has no idempotency receipt. After an uncertain result, GET sources and
points before retry; duplicate source ID is not a defined replay.

## 5. List envelopes

### Sources

`GET .../survey-sources/?include_inactive=1`. No pagination, count, total, or
truncated marker. Without `include_inactive=1`, only active rows are returned.

```json
{
  "ok": true,
  "project_id": "11111111-1111-4111-8111-111111111401",
  "sources": [{
    "id":"30000000-0000-4000-8000-000000000002","project_id":"11111111-1111-4111-8111-111111111401",
    "source_group_id":"30000000-0000-4000-8000-000000000001","supersedes_id":null,
    "source_type":"TOTAL","original_file_name":"survey.csv","original_file_key":null,
    "imported_at":"2026-10-01T12:00:00+00:00","imported_by":null,"source_crs":"EPSG:5186",
    "geoid_model":null,"calibration_info":{},"version":1,"is_active":true,"note":""
  }]
}
```

### Points

`GET .../survey-points/?source_id={uuid}`; `source_id` is optional. It silently
returns at most 5,000 rows ordered by `source_row_id,id`, with no pagination,
count, total, or truncated marker. Exactly 5,000 rows must not be treated as a
complete inventory.

```json
{
  "ok": true,
  "project_id": "11111111-1111-4111-8111-111111111401",
  "points": [{
    "id":"50000000-0000-4000-8000-000000000001","source_id":"30000000-0000-4000-8000-000000000002",
    "source_row_id":"P001","raw_x":"200000.120","raw_y":"500000.340","raw_z":"12.300",
    "raw_crs":"EPSG:5186","raw_code":"DEP","raw_geoid_model":null,
    "x":"200000.120","y":"500000.340","z":"12.300","longitude":127.123,"latitude":36.456,
    "updated_at":"2026-10-01T12:00:00+00:00"
  }]
}
```

No GeoJSON/WKT `geom`, source version/group, `raw_data`, worker, date, or method
is returned. Geometry is longitude/latitude; join source metadata by `source_id`.

### Links

`GET .../survey-links/?survey_id=&layer=&target_id=&include_unlinked=1&limit=1000`.
`layer` is standard name. Limit defaults to 1,000 and must be 1..5,000. There is
no offset/cursor/count/total/truncated. Unlinked rows require the explicit flag.

```json
{
  "ok": true,
  "protocol": "survey_link_v1",
  "project_id": "11111111-1111-4111-8111-111111111401",
  "links": [{
    "id":"40000000-0000-4000-8000-000000000003","survey_id":"50000000-0000-4000-8000-000000000001",
    "layer_id":"70000000-0000-4000-8000-000000000001","layer":"WTL_VALV_PS","physical_name":"wtl_valv_ps",
    "target_id":"60000000-0000-4000-8000-000000000001","match_method":"manual",
    "match_distance":null,"match_confidence":null,"confirmed_by":null,"confirmed_at":"2026-10-01T12:00:00+00:00",
    "created_at":"2026-10-01T12:00:00+00:00","vertex_index":null,"link_role":"POINT",
    "link_status":"LINKED","updated_at":"2026-10-01T12:00:00+00:00","updated_by":null
  }]
}
```

Rows have no project revision or row version/ETag.

## 6. Survey-link Changesets

POST `.../survey-link-changesets/`. `client_id` and `changeset_id` are required
UUIDs. Optional non-negative `base_revision` is rejected only when ahead of the
server; it is not an equality lock. `changes` is atomic.

### Create

```json
{
  "client_id":"40000000-0000-4000-8000-000000000001","changeset_id":"40000000-0000-4000-8000-000000000002","base_revision":17,
  "changes":[
    {"action":"create","id":"40000000-0000-4000-8000-000000000003","survey_id":"50000000-0000-4000-8000-000000000001","layer":"WTL_VALV_PS","target_id":"60000000-0000-4000-8000-000000000001","match_method":"manual","link_role":"POINT","link_status":"LINKED"},
    {"action":"create","id":"40000000-0000-4000-8000-000000000004","survey_id":"50000000-0000-4000-8000-000000000002","standard_name":"WTL_PIPE_LM","target_id":"60000000-0000-4000-8000-000000000002","match_method":"manual","link_role":"VERTEX","vertex_index":1}
  ]
}
```

`layer` and `standard_name` are aliases; send one. Defaults are POINT/LINKED.
Survey and target must already exist and layer must be in the current Layer Plan.

### Update/manual movement/remap

Only `link_status`, `link_role`, and `vertex_index` are mutable:

```json
{"action":"update","id":"40000000-0000-4000-8000-000000000004","link_status":"MANUALLY_MODIFIED"}
```

`survey_id`, layer, `target_id`, match fields, and IDs cannot be changed. To
change identity, unlink old and create a new mapping UUID. `KEEP_LINK` means
`LINKED`; `MARK_MANUAL` means `MANUALLY_MODIFIED`.

### Unlink/delete

```json
{"action":"unlink","id":"40000000-0000-4000-8000-000000000004"}
```

Unlink preserves the row as `UNLINKED`. Legacy
`{"action":"delete","id":"..."}` physically removes only the mapping. There
is no standalone HTTP DELETE endpoint. New clients use unlink.

### Success, atomicity, idempotency

```json
{
  "ok":true,"protocol":"survey_link_changeset_v1","resource_kind":"relation",
  "project_id":"11111111-1111-4111-8111-111111111401","client_id":"40000000-0000-4000-8000-000000000001",
  "changeset_id":"40000000-0000-4000-8000-000000000002","base_revision":17,
  "first_revision":18,"last_revision":19,"current_revision":19,
  "created":2,"deleted":0,"updated":0,"unlinked":0,"total":2,
  "applied":[
    {"revision":18,"resource_kind":"relation","action":"create","layer":"SURVEY_LINK","id":"40000000-0000-4000-8000-000000000003"},
    {"revision":19,"resource_kind":"relation","action":"create","layer":"SURVEY_LINK","id":"40000000-0000-4000-8000-000000000004"}
  ],"replayed":false
}
```

There is no partial success. Any failure rolls back all changes. HTTP 409 has
`conflicts`; HTTP 400 has `message` and `details`.

`(project_id,client_id,changeset_id)` is idempotent. After a lost response,
retry with the same IDs; the stored response returns with `replayed=true`
without new revisions. Never reuse a committed pair for different content.

## 7. Feature Changeset ordering and recovery

Feature and link Changesets are separate transactions; there is no cross-API
two-phase commit or rollback. Required order for new features/split results:

1. Generate final feature UUID locally.
2. Commit feature create/geometry Changeset.
3. After success, submit link creates/remaps using that UUID/current indexes.
4. Apply/fetch returned project revisions in order.

If feature save fails, do not send links. If link save fails, feature geometry
stays committed; queue/retry the link Changeset. After a crash/unknown response,
retry with the original IDs so the receipt resolves replay.

For vertex insertion/deletion, commit geometry first, then all index updates in
one link Changeset. Old indexes may be temporarily stale; do not reapply before
remap succeeds. On split, QGIS owns ancestry, target selection, new vertex
indexes/mapping UUIDs, and unlinking superseded mappings. The server validates
but does not infer or redistribute mappings.

## 8. Reapply

Both endpoints accept `source_id` **or** non-empty `survey_ids`; optional
`mapping_ids` restricts either selection.

```json
{"source_id":"30000000-0000-4000-8000-000000000002","mapping_ids":["40000000-0000-4000-8000-000000000003"]}
```

### Preview

POST `.../survey-reapply-preview/` returns:

```json
{
  "ok":true,"project_id":"11111111-1111-4111-8111-111111111401",
  "counts":{"applicable":1,"manually_modified":1,"unlinked":1,"invalid":0},
  "items":[{
    "mapping_id":"40000000-0000-4000-8000-000000000003","survey_id":"50000000-0000-4000-8000-000000000001",
    "layer_id":"70000000-0000-4000-8000-000000000001","layer":"WTL_VALV_PS",
    "feature_id":"60000000-0000-4000-8000-000000000001","vertex_index":null,"link_role":"POINT",
    "link_status":"LINKED","classification":"applicable","reason":null
  }]
}
```

Counts are mapping counts, not distinct Survey/feature counts. POINT/VERTEX
totals are not separate; derive from items. Classifications are `applicable`,
`manually_modified`, `unlinked`, `invalid`. Invalid reasons include
`layer_outside_current_plan`, `survey_or_target_missing`,
`survey_geometry_missing`, `point_role_geometry_mismatch`, and
`vertex_out_of_range_or_not_linestring`. Preview mutates nothing and issues no
preview token or revision lock.

### Execute

POST `.../survey-reapply/` accepts the same selection. Optional `client_id` and
`changeset_id` are only audit identities (generated if absent). Reapply has no
changeset receipt, idempotent replay, preview token, or expected revision.

```json
{
  "ok":true,"project_id":"11111111-1111-4111-8111-111111111401","applied":1,
  "skipped":[{"mapping_id":"40000000-0000-4000-8000-000000000004","reason":"manually_modified"}],
  "first_revision":20,"last_revision":20,"current_revision":20
}
```

Only LINKED applies. MANUALLY_MODIFIED, UNLINKED, and plan mismatch are skipped.
POINT replaces a point; VERTEX uses `ST_SetPoint` only at the mapped index.
Missing target/Survey geometry, invalid role/index, or invalid result aborts and
rolls back all. Successful feature IDs are not returned; use fresh preview items
and the revision range, then Delta. For uncertain execute results, reconcile via
Delta/current revision and fresh preview—do not blindly retry.

## 9. Errors

| HTTP | Code | Meaning |
|---:|---|---|
| 400 | `survey_rejected` | invalid source/CRS/input/selection/reapply |
| 400 | `survey_source_object_invalid` | uploaded object invalid |
| 400 | `survey_link_rejected` | invalid mapping Changeset |
| 403 | Django permission response | tenant/project/write denial |
| 409 | `survey_conflict` | source/reapply conflict |
| 409 | `survey_link_conflict` | mapping/referenced-object conflict |
| 503 | `survey_failed` | Survey DB unavailable |
| 503 | `survey_link_unavailable` | Changeset receipt/runtime unavailable |
| 503 | `survey_link_failed` | Survey-link DB unavailable |

Source/Survey FKs use RESTRICT and cannot cascade into facilities. There is no
source/Survey deletion endpoint in v1.

## 10. Earlier brief vs deployed contract

| Topic | Earlier implication | Deployed/final contract |
|---|---|---|
| Presign | URL names unspecified | `presigned_url`, `object_key`, `headers`; PUT; 900 s |
| File import | server might parse file | server verifies file; client supplies parsed `points` |
| Working CRS | project scope might supply it | no lookup; client sends EPSG, server transforms once |
| Point cap | 5,000 cap | silent LIMIT; no count/total/truncated/pagination |
| Worker/date/method | requested metadata | not mapped to dedicated columns; optional preservation in `raw_data` |
| Mapping update | state transition example | only status/role/vertex mutable; identity immutable |
| Unlink | delete wording ambiguous | unlink preserves; legacy delete removes only mapping |
| Feature/link order | omitted | feature/geometry first, link second; no cross-API rollback |
| Preview | generic counts/IDs | exact mapping items; no token/revision lock |
| Execute retry | unclear | atomic but no receipt; reconcile via Delta/fresh preview |

## 11. Connector handoff boundary

The Connector may implement adapters, presign/PUT, source parsing, browsing,
link queueing, manual status, and reapply UI from this document. It owns:

- correct TM EPSG selection;
- CSV/XLSX parsing into `points`;
- optional unsupported source metadata preservation in `raw_data`;
- feature-before-link ordering and durable retries;
- vertex remap and split mapping redistribution;
- uncertain non-idempotent import/reapply reconciliation.

It must not infer pagination, a project working-CRS API, server-side file
parsing, preview tokens, cross-API atomicity, stable vertex UUIDs, or automatic
split/remap behavior.
