# GeoFlow GIS Survey lineage contract v1

Status: **server final-field extension implemented; production verification pending**.
The existing lineage/delete contract remains deployed. Its earlier upload
baseline was release `4c5fc553339bdf429b8ec5c6d656a414be484f6d`. The extension below is
based on a read-only production inventory from run `38882883940` (PR #415).
QGIS Connector and QField changes are out of scope.

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

The import contract never defaults a Korean TM zone. For each point, send either:

1. `longitude` and `latitude`, treated as EPSG:4326; or
2. `raw_x` and `raw_y`, plus `EPSG:n` in point `raw_crs` or source `source_crs`.

Point `raw_crs` overrides source `source_crs`. For TM-only input, the Connector
must obtain/configure the correct EPSG and send it. PostGIS performs the sole
`ST_Transform(...,4326)`; QGIS must not transform the same ordinates again.
Missing/invalid CRS returns HTTP 400 `survey_rejected`. When longitude/latitude
are present they determine geometry even if raw values are also present; the
server does not cross-check the two representations.

Final `x/y` use PostGIS X=Easting and Y=Northing, with no axis swap. Projected
raw ordinates are retained as final planar ordinates. Geographic raw input and
longitude/latitude-only input are transformed from stored EPSG:4326 geometry to
an explicit projected `target_crs`, otherwise projected source `source_crs`,
otherwise the single distinct projected CRS in this project's non-deleted source
metadata (`target_crs` then `source_crs`). Missing or ambiguous projected CRS
returns `survey_rejected`; it never stores degrees as final planar coordinates.
The resolved batch fallback is stored as Source `target_crs`. Raw point CRS may
differ from that fallback; projected raw points always keep their own ordinates.

CRS availability/classification is queried once per batch. Numeric inputs must
be finite, complete coordinate pairs are required, and EPSG:4326 longitude and
latitude are range checked. `z` starts from `raw_z`; there is no existing server
geoid/antenna correction to apply. Raw values remain unchanged. Missing values
stay NULL, and genuine zero values remain zero.

## 2. Storage contract

### `gis.survey_source`

| Field | Type | Null | Meaning |
|---|---|---:|---|
| id | uuid PK | no | immutable source version ID |
| project_id | uuid | no | tenant project |
| source_group_id | uuid | no | stable lineage/series ID |
| supersedes_id | uuid FK | yes | prior active source version |
| source_type | varchar(20) | no | `GNSS`, `GPS`, `TOTAL`, `CSV`, `XLSX`, `OTHER` |
| survey_type | varchar(20) | yes | explicit measurement method: `GNSS` / `TOTAL_STATION` |
| target_crs | text | yes | resolved projected fallback CRS for geographic input |
| original_file_name | text | no | audit/display name |
| original_file_key | text | yes | private storage reference |
| imported_at/imported_by | timestamptz/uuid | no/yes | server audit |
| source_crs | text | yes | normally `EPSG:n` |
| geoid_model | text | yes | geoid identifier |
| calibration_info | jsonb object | no | calibration metadata |
| version | integer | no | positive group version |
| is_active | boolean | no | one active version per group/project |
| note | text | no | default empty string |

`source_type` historically mixes instrument (`GNSS`, `GPS`, `TOTAL`) and file
(`CSV`, `XLSX`, `OTHER`) classifications. Its accepted domain is preserved for
existing clients. New optional import metadata `survey_type` separates method
from file type. Recognized aliases `GPS` and `TOTAL` normalize to `GNSS` and
`TOTAL_STATION`; `TotalStation` is also accepted. Explicit invalid methods are
rejected. Without explicit metadata, recognized legacy source methods derive the
point type. A file type alone does not imply an instrument method.

A revision inserts a row, deactivates the prior active version, retains
`source_group_id`, and requires the immediately preceding active row as
`supersedes_id`.

### `gis.survey`

Lineage additions are `source_id uuid NULL`, `source_row_id text NULL`,
`raw_crs text NULL`, `raw_code text NULL`, and `raw_geoid_model text NULL`.
During revision, `(project, source_group_id, source_row_id)` retains the logical
Survey UUID while coordinates and `source_id` advance.

Import maps the following dedicated fields. Fields not listed remain legacy or
reserved and must not be inferred from similarly named source columns.

| Field | PostgreSQL type / null | Client input | Server rule |
|---|---|---|---|
| worker_id | uuid / yes | point, then request fallback | validates UUID, tenant employee existence, and shared GIS assignment authorization; no physical employee FK is added |
| survey_date | date / yes | point, then request fallback | accepts only ISO `YYYY-MM-DD`; never defaults to today |
| name | varchar(30) / yes | point | trimmed string; defaults to `source_row_id` only when that value is at most 30 characters |
| code | varchar(30) / yes | point | trimmed string; defaults to `raw_code` only when that value is at most 30 characters |
| raw_x/raw_y/raw_z | numeric(20,3) / numeric(20,3) / numeric(10,3), all yes | point | source Easting/Northing/height preserved unchanged |
| survey_no | varchar(30) / yes | server only | project/date number `YYMMDD-NNN`; unknown date stays NULL |
| type | varchar(20) / yes | batch `survey_type`, then legacy method-valued `source_type` | `GNSS` / `TOTAL_STATION`; unknown method stays NULL |
| x/y/z | numeric(20,3) / numeric(20,3) / numeric(10,3), all yes | server only | planar raw x/y preserved, geographic input transformed to resolved projected CRS; z from raw_z |
| longitude/latitude | double precision / yes | a complete pair may define input geometry | both non-null values take precedence over raw coordinates; the server validates finite/range bounds and always overwrites both from normalized EPSG:4326 `geom` after insert/update |
| solution_info | varchar(200) / yes | point | trimmed string; maximum 200 characters |
| pdop | double precision / yes | point | numeric or numeric string; must be finite and non-negative |
| antenna_height | numeric(8,3) / yes | point | numeric or numeric string; must be finite and non-negative and fit the DB numeric type |
| raw_data | jsonb / no, default `{}` | point | omitted, null, or another JSON-falsy value is normalized to `{}`; any truthy non-object is rejected; stores unmodeled source metadata |

Point-level values override request-level `worker_id` and `survey_date`.
`imported_by` remains the authenticated source-import audit identity and is not
the Survey worker. The authenticated assignment rule is the same one used by
feature Changesets: a non-manager may assign only their linked employee ID; a
project manager may assign any non-deleted tenant employee. Invalid or
unauthorized IDs return `survey_rejected`. Client-supplied longitude/latitude may define input geometry,
but stored longitude/latitude are derived back from `geom` after normalization.
`surveyed_at`, `survey_code`, and `filter` are not import fields;
preserve such input in `raw_data` rather than guessing legacy semantics.

The complete accepted point-key set is `id`, `source_row_id`, `raw_x`, `raw_y`,
`raw_z`, `raw_crs`, `raw_code`, `raw_geoid_model`, `longitude`, `latitude`,
`raw_data`, `worker_id`, `survey_date`, `name`, `code`, `solution_info`, `pdop`,
and `antenna_height`. An unknown top-level point key rejects the whole import.
Empty strings for `worker_id`, `survey_date`, `name`, `code`,
`solution_info`, `pdop`, and `antenna_height` are treated as null.

#### Client-supplied versus server-generated point values

- The client must send `source_row_id` and one geometry input form: a complete
  longitude/latitude pair, or raw_x/raw_y plus an EPSG CRS. Optional import
  fields are the other keys in the accepted set above.
- Point `id` may be supplied for a new logical row; otherwise the server creates
  it. On a source revision the server retains the existing logical Survey UUID.
- The server assigns `source_id`, `survey_no`, `type`, and final x/y/z, constructs
  `raw_geom` and `geom`, then derives stored longitude/latitude from `geom`.
- The point-key allowlist intentionally continues rejecting `survey_no`, `type`,
  and `x/y/z`: clients send inputs, and the server generates final fields.
- The server creates `created_at`/`updated_at`, project revisions, change-log
  rows, and the internal changeset receipt. Clients do not send those values.
- Source-level `worker_id` and `survey_date` are fallback inputs only. A point
  value, including an explicit null/empty value, takes precedence when the key
  is present.

Repository schema, package exclusions, GeoJSON candidates, lineage services, and
legacy columns yield this classification:

| Class | Fields | Current meaning/use |
|---|---|---|
| A — active lineage | source_id, source_row_id, raw_x/y/z, raw_crs, raw_code, raw_geoid_model, geom | import identity, raw ordinates, canonical EPSG:4326 point, revision/reapply/link lookup |
| A — active attribution | worker_id, survey_date, name, code, longitude, latitude | imported attribution, source-list aggregation, point API and legacy display compatibility |
| A — server final interpretation | survey_no, type, x/y/z | stable project/day number, measurement method, final planar ordinates and height |
| B — legacy geometry duplicate | raw_geom | mirrors normalized geom and is excluded from scalar QGIS form attributes |
| C — optional instrument input | solution_info, pdop, antenna_height, raw_data | validated optional GNSS/device metadata; `raw_data` is JSONB (`rawdata` is not a DB column) |
| D — meaning not established | survey_code, surveyed_at, filter, description | existing nullable legacy/reserved columns; import rejects these top-level point keys |

No field in class D is automatically populated or reinterpreted by this
contract. The duplicate class remains for compatibility and is not a proposal
to add or remove physical columns.

### Final-field allocation, reads and operational backfill

`_point_metadata()` and `_POINT_FIELDS` in `geoflow_ops/gis/survey_sources.py`
are the exact source of the previous HTTP 400 unsupported-field response.
Their derived-field rejection remains intentional. `survey_final.py` owns
coordinate/method/number interpretation; `survey_sources.py` stores and logs it.

Import holds the existing `gis.project_sync_state` row `FOR UPDATE` throughout
the transaction, shared with other GIS writers. One grouped maximum query reads
all retained number prefixes (including soft-deleted points); in-memory counters
allocate numbers by survey date for the whole batch. `survey_project_no_uq`
enforces `(project_id,survey_no)` uniqueness. Number padding is at least three
digits and continues beyond 999. Source revisions retain logical UUID and any
existing number even if the date changes. New rows, and formerly unnumbered
rows with a supplied date, receive a number. Unknown dates are never replaced
with import date or today.

One import transaction includes Source version, Point creation/update, numbering,
final interpretation, revision log and receipt. A failure rolls everything back.
Existing logical points and tenant employee IDs are prefetched once per batch;
there is no per-point source, number maximum or CRS configuration lookup.

Import responses add `points` containing IDs and persisted full values. Point
list readback adds `survey_no/type`. Survey create/update Delta `attributes` now
include the full final-field set and all existing raw/instrument/date/code fields.
Numeric Delta/import attributes use the existing `_plain_value` JSON-number
convention; the Point GET API retains Django's numeric-string convention.
GeoPackage SELECTs already derive from central Final Form fields, which include
all required final fields. The deploy updates only Survey derived-field readonly
flags; the resulting definition revision and backfill revisions invalidate old
server snapshot fingerprints without deleting source/package metadata.

Read-only production inventory on 2026-10-16:

- Three active tenants: two have no Survey rows; one has 389.
- All required columns, including `survey_no`, already exist and have no defaults.
- All 389 points lack number and method; 22 lack survey_date.
- All 389 raw CRSs are EPSG:5186; no raw-present NULL/zero final coordinates
  were found. Source types are 14 CSV and 2 GNSS sources.
- Existing number duplicates: 0. No existing Survey method domain constraint.
- Central Survey definitions already contain all required final fields.
- Tenant project_definition has selections/overrides/revision, with no CRS field.

`0046_gis_survey_final_fields` adds missing survey_no only for fresh foundations,
Source method/target metadata and the unique/method constraints. It does not
rewrite provenance. `deploy_gis_survey_final_fields --apply --backup-dir ...`
first checks every tenant, privately backs up scalar Survey rows and affected
central fields, then applies exact additive SQL/history and runs
`survey_backfill.backfill_survey_project` under normal project locks.

Backfill order is survey_date, created_at, UUID. Existing numbers and valid final
values are protected. Missing planar values may come from projected raw values;
missing geographic values, or proven copies of EPSG:4326 degrees, require a
reliably resolved projected CRS. Missing z comes from raw_z. Missing lat/lon
comes from geometry. Method uses only recognized, consistent source/explicit raw
method metadata. Missing dates/methods/ambiguous CRS are counted and left NULL;
zero is preserved because the investigated schema has no zero defaults. Each
changed row gets a full ordinary Delta update and receipt. Reruns are idempotent.
No Source/facility deletion policy or Connector code is changed.

Rollback: schema additions use a non-destructive reverse noop. Once schema/data
are committed, deploy does not silently roll code back. The private per-run
backup is the basis for a reviewed targeted recovery; normal source UUIDs,
geometry, raw data, and deletion relationships are unchanged.

Verification: disposable PostGIS rehearsal covers 22+3, GNSS/TOTAL_STATION,
mixed dates, geographic normalization, NULL/zero, source revision identity,
rollback, uniqueness, simultaneous imports, idempotent backfill, Delta and
materialized GeoPackage values, plus 500-point lookup counts. Production upload
smoke checks actual presign/import/readback, 22 GNSS+3 TotalStation numbering,
Delta and central-definition-derived GeoPackage values, then rolls test DB writes
back and removes its temporary S3 object. Operational results are recorded after
execution; code availability alone is not production verification.

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
fail-closed, and require `maps.view`. POST and DELETE also require project GIS write
access. JSON uses `Content-Type: application/json`. Source bodies are limited to
20 MiB; Survey-link Changesets to 5 MiB.

| Purpose | Method and endpoint |
|---|---|
| sources/presign/import | `GET/POST /gis/projects/{project_id}/api/survey-sources/` |
| source delete precheck/delete | `GET/DELETE /gis/projects/{project_id}/api/survey-sources/{source_id}/` |
| points | `GET /gis/projects/{project_id}/api/survey-points/` |
| mappings | `GET /gis/projects/{project_id}/api/survey-links/` |
| mapping Changeset | `POST /gis/projects/{project_id}/api/survey-link-changesets/` |
| reapply preview | `POST /gis/projects/{project_id}/api/survey-reapply-preview/` |
| reapply execute | `POST /gis/projects/{project_id}/api/survey-reapply/` |

Only Survey-link list/Changeset also have `/api/qfield/` routes. Source import,
point list, and reapply have no QField route in v1.

## 4. Source presign, import, and deletion

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

The response deliberately has no `method`, `expires_in`, or multipart `fields`
member. The method is always `PUT`, and this is an S3 presigned PUT rather than
a presigned POST. `project_id` is taken only from the URL. `id`, filename, and
MIME are supplied by the client as shown above; when `id` is omitted the server
generates it.

The deployed server has no extension/MIME allowlist for this endpoint. The
Connector should use these conventional values and must repeat the exact
returned `Content-Type` header on PUT when it supplied a MIME type:

| File | MIME |
|---|---|
| CSV | `text/csv` |
| XLS | `application/vnd.ms-excel` |
| XLSX | `application/vnd.openxmlformats-officedocument.spreadsheetml.sheet` |

Filename extensions `csv`, `xls`, and `xlsx` are all preserved in the object
key. The source enum has `CSV` and `XLSX` but no `XLS`; an XLS workbook may be
archived with its XLS MIME while the parsed import must use a supported
`source_type` (normally `OTHER`, unless the product chooses another existing
semantic type). MIME is signed and recorded by S3 but is not compared during
finalization. There is no Survey-specific upload byte limit in the presign or
HEAD path; the non-zero check is the only object-size rule. The **import JSON**,
not the S3 object, is limited to 20 MiB.

#### File upload result

Send the raw file bytes, not multipart form data:

```http
PUT <presigned_url>
Content-Type: text/csv
x-amz-server-side-encryption: AES256

<raw file bytes>
```

Treat any HTTP 2xx response as transport success; AWS S3 `PutObject` normally
returns HTTP 200 with an empty response body. Do not parse a JSON response.
Final success is established only when the following import POST succeeds,
because that call performs the server-side HEAD verification.

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
  "worker_id": "80000000-0000-4000-8000-000000000001",
  "survey_date": "2026-10-01",
  "calibration_info": {"control_set":"2026-10"},
  "note": "recalibrated",
  "points": [
    {"id":"50000000-0000-4000-8000-000000000001","source_row_id":"P001","raw_x":200000.12,"raw_y":500000.34,"raw_z":12.3,"raw_code":"DEP","name":"P001","code":"DEP","solution_info":"FIX","pdop":1.2,"antenna_height":1.8,"raw_data":{"method":"TOTAL"}},
    {"source_row_id":"P002","longitude":127.123,"latitude":36.456,"raw_z":12.1,"worker_id":"80000000-0000-4000-8000-000000000002","survey_date":"2026-10-02"}
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
Import has no client-supplied or replayable idempotency key. The server creates
an internal changeset receipt for change-log integrity, but it is not an import
retry token. After an uncertain result, GET sources and
points before retry; duplicate source ID is not a defined replay.

The response is HTTP 200. `created + updated` is the number of submitted point
rows committed. There are no `skipped`, `rejected`, `errors`, or row-result
members. `source_id` is the value to select in the source list and to pass as
`GET .../survey-points/?source_id={source_id}`. A 10-row Connector preview has
no server meaning: every item in the submitted `points` array is processed.

### Source failure envelopes

Representative deployed responses are:

```json
{"ok":false,"error":"survey_source_object_invalid"}
```

HTTP 400 for a missing/empty/encryption-mismatched uploaded object.

```json
{"ok":false,"error":"survey_rejected","message":"points must be a non-empty list","details":null}
```

HTTP 400 for validation failures, including duplicate `source_row_id`, invalid
coordinates/CRS, invalid `source_type`, an absent filename, or an oversized
JSON body. Invalid worker UUIDs, unauthorized worker assignment, non-ISO dates,
unknown point keys, overlong strings, and invalid optional numerics use this
same envelope. Validation messages are stable enough for diagnostics but the UI
should primarily branch on `error`.

```json
{"ok":false,"error":"survey_conflict","conflicts":[{"resource_kind":"survey_source","id":"<uuid>","reason":"superseded_source_missing_or_wrong_group"}]}
```

HTTP 409 for a source revision conflict. Database failures return HTTP 503
`{"ok":false,"error":"survey_failed"}`. Authentication/tenant/project
permission rejection follows the shared Django authorization response rather
than a Survey JSON envelope; the Connector must preserve its normal session and
permission handling.

### Source and Survey Point soft deletion

```http
GET    /gis/projects/{project_id}/api/survey-sources/{source_id}/
DELETE /gis/projects/{project_id}/api/survey-sources/{source_id}/?mode=source_and_points
GET    /gis/projects/{project_id}/api/survey-points/{survey_id}/
DELETE /gis/projects/{project_id}/api/survey-points/{survey_id}/
POST   /gis/projects/{project_id}/api/survey-points/bulk-delete/
```

GET requires `maps.view`; mutations additionally require the existing project
GIS write permission. Source DELETE soft-deletes the Source and every visible
point belonging to it in one tenant transaction. `source_and_points` is the
canonical mode. Missing mode and legacy `mode=source_only` have the same safe
Source + Points meaning so deployed Connector builds do not need a workaround.

```json
{"ok":true,"project_id":"11111111-1111-4111-8111-111111111401","delete":{"source_id":"30000000-0000-4000-8000-000000000002","source_group_id":"30000000-0000-4000-8000-000000000002","supersedes_id":null,"version":1,"is_active":true,"point_count":22,"links":{"LINKED":2,"MANUALLY_MODIFIED":0,"UNLINKED":1},"linked_target_count":3,"linked_facility_count":3,"depth_dependency_count":0,"child_version_count":0,"shared_object_reference_count":0,"has_archived_object":true,"object_key_valid":true,"can_delete":true,"blocked_reason":null}}
```

Links in every status and Source version lineage are impact information, not
blockers. The server retains every facility and `gis.survey_link` row. Source
and Point rows receive `deleted_at`, `deleted_by`, and `delete_reason`; the
Source also receives `is_active=false`. No FK uses CASCADE. Existing link reads
mark retained provenance with `survey_deleted:true`.

### Facility deletion with Survey provenance

A facility target may be deleted through the normal GIS Changeset even when an
active `gis.survey_link` points to it. In the same tenant transaction, active
links become `UNLINKED`, their `updated_at`/`updated_by` audit is recorded, the
GIS feature is deleted, and the normal feature change log and revision are
written. The Survey Point and Survey Source remain unchanged.

`UNLINKED` is the existing inactive-link state and remains queryable as
historical provenance. The active-target unique index and create duplicate
guard already exclude it, so the same Survey Point can create a new facility
after its former target is deleted. A delete batch detaches all matching links
with one set-based update before applying feature deletes; any later failure
rolls back both. `survey_links_exist` is no longer a facility-delete conflict.
Real missing-object, permission, stale-state, and concurrent-change conflicts
remain protected.

```json
{"ok":true,"source_id":"30000000-0000-4000-8000-000000000002","source_deleted":true,"survey_points_deleted":22,"deleted_point_count":22,"facilities_deleted":0,"facility_links_preserved":3,"linked_facilities_preserved":3,"depth_dependency_count":0,"deleted_object":true,"cleanup_pending":false,"first_revision":20,"last_revision":41,"current_revision":41}
```

The private S3 object is deleted after the DB commit only when its key has the
exact tenant/project/source prefix and is not shared. A missing object needs no
request. Storage cleanup failure does not roll back the DB: HTTP 200 contains
`deleted_object:false,cleanup_pending:true`. The response never exposes the key.

Point precheck uses GET for one ID or bulk POST
`{"action":"precheck","survey_ids":["..."]}`. Bulk delete uses
`{"action":"delete","survey_ids":["..."]}` (action may be omitted):

```json
{"ok":true,"project_id":"11111111-1111-4111-8111-111111111401","delete":{"survey_count":3,"source_ids":["30000000-0000-4000-8000-000000000002"],"links":{"LINKED":1,"MANUALLY_MODIFIED":0,"UNLINKED":1},"linked_facility_count":2,"depth_dependency_count":0,"can_delete":true}}
```

```json
{"ok":true,"survey_points_deleted":3,"linked_facilities_preserved":2,"facility_links_preserved":2,"facilities_deleted":0,"depth_dependency_count":0,"first_revision":42,"last_revision":44,"current_revision":44}
```

Every requested point must be visible and belong to the URL project; otherwise
the atomic operation returns HTTP 400 `survey_rejected`. A missing/already
deleted Source returns 404 `survey_source_not_found`. DB failures return 503
`survey_source_delete_failed` or `survey_point_delete_failed`.

Deleted points are excluded from normal Source/Point lists, map reads,
GeoPackages, new-link validation, reapply, and future Nearby/depth candidates.
The deployed schema has no explicit depth-dependency table, so
`depth_dependency_count` is currently 0. Historical facility `pip_dep` values
are never changed or recalculated. Reimport creates a new Source/Point set;
deleted rows do not participate in active matching.

### Production upload smoke

The protected operational smoke uses the deployed view/service/storage path:
presign, real encrypted S3 PUT, import of 22 mixed EPSG:4326/EPSG:5186 points,
source list, filtered point list, metadata checks, deletion precheck, and DELETE.
Deferred constraints are forced immediate before the outer rollback. Tenant DB
writes run inside that rollback transaction and the temporary S3 object is
deleted; no test Survey data remains. The smoke reports only field
names/counts/status and never prints the presigned URL, object key, credentials,
or session data.

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
    ,"point_count":2,"survey_date_from":"2026-10-01","survey_date_to":"2026-10-02",
    "worker_count":2,"workers":[{"id":"80000000-0000-4000-8000-000000000001","name":"Surveyor A"}]
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
    "worker_id":"80000000-0000-4000-8000-000000000001","survey_date":"2026-10-01",
    "name":"P001","code":"DEP","solution_info":"FIX","pdop":1.2,
    "antenna_height":"1.800","raw_data":{"method":"TOTAL"},
    "updated_at":"2026-10-01T12:00:00+00:00"
  }]
}
```

No GeoJSON/WKT `geom` or source version/group is returned. `survey_no` and
`type` are included; type is the dedicated measurement method.
Geometry is longitude/latitude; join source metadata by `source_id`.

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
| 404 | `survey_source_not_found` | project-scoped source missing |
| 409 | `survey_link_conflict` | mapping/referenced-object conflict |
| 503 | `survey_failed` | Survey DB unavailable |
| 503 | `survey_source_delete_failed` | Source/Point soft-delete transaction failed and rolled back |
| 503 | `survey_point_delete_failed` | individual/bulk Point soft-delete failed and rolled back |
| 503 | `survey_link_unavailable` | Changeset receipt/runtime unavailable |
| 503 | `survey_link_failed` | Survey-link DB unavailable |

Source/Survey FKs remain RESTRICT and cannot cascade into facilities. Delete
endpoints update only Survey source/point deletion metadata and preserve links.

## 10. Earlier brief vs deployed contract

| Topic | Earlier implication | Deployed/final contract |
|---|---|---|
| Presign | URL names unspecified | `presigned_url`, `object_key`, `headers`; PUT; 900 s |
| File import | server might parse file | server verifies file; client supplies parsed `points` |
| Working CRS | project scope might supply it | explicit target, projected source, or unambiguous project source metadata; never a hardcoded zone |
| Point cap | 5,000 cap | silent LIMIT; no count/total/truncated/pagination |
| Worker/date/method | requested metadata | worker/date/instrument fields mapped; final method from explicit or recognized legacy source method |
| Source delete | no endpoint | GET impact precheck + atomic Source/Point soft delete; links/facilities retained |
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

### Deployment recovery from the 2026-10-16 preflight failure

Deployment `38885511180` checked out `d736eaf` but stopped in the older lineage
inventory with `UndefinedColumn` before executing the final-field migration.
Its failure handler restarted the service; this was a deployment failure after
GitHub approval, not an approval rejection. The legacy elevation inventory now
inspects available code columns rather than requiring optional `survey_code`.
No Source/Point/facility deletion behavior changes.

Every deploy also runs `deploy_gis_survey_final_fields --check` read-only before
stopping the service. It checks actual tenant migration history and required
columns/constraints. A missing final-field migration schedules the reviewed
transition and full Survey smoke even when the previous attempt already checked
out the same application code. A file-only diff cannot establish DB readiness.
The command rechecks additive schema shape on apply, keeps original backups,
and can safely resume partially completed tenant deployment. Recovery results
remain pending until the protected production run and smoke succeed.

### 2026-10-17 applied DB state and definition verification

Run `38887530489` successfully applied migration 0046 to all three tenants and
committed the Survey backfill: 367 numbers, 32 recognized measurement methods,
and longitude/latitude on 22 points. It examined 389 points and changed all 389
for at least one of those fields. Dates remain unknown on 22 points; methods
remain unknown on 357. Existing planar/height/raw values were preserved. A second
backfill pass after restart changed zero rows across all five populated projects.

The later central definition inventory rejected the intentional readonly changes
on the five derived Survey fields. Code and DB changes remain applied; the
failure handler restarted the service. Upload/Delta/materialized-package
production smoke had not yet executed, so full production verification is pending.

The inventory's explicit `--survey-final-readonly` transition mode fingerprints
the expected readonly=true state for exactly survey_no/type/x/y/z of the Survey
layer and permits their updated_at audit changes. Compare still requires actual
readonly=true, unchanged counts, all other attributes and every other inventoried
row/table. The default code-only inventory remains fully strict. The workflow
uses the same explicit mode before and after an authorized Survey transition;
it does not skip or globally relax definition comparison. Real PostGIS tests
accept those five changes and reject wrong readonly values or unrelated edits.
