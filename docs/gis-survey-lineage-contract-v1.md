# GeoFlow GIS Survey lineage contract v1

Status: **deployed server/tenant contract**. This document describes PR #392,
deployed release `4c5fc553339bdf429b8ec5c6d656a414be484f6d`. QGIS Connector
and QField UI are out of scope. A client must not infer capabilities marked
unsupported here.

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

Import maps the following dedicated fields. Fields not listed remain legacy or
reserved and must not be inferred from similarly named source columns.

| Field | PostgreSQL type / null | Client input | Server rule |
|---|---|---|---|
| worker_id | uuid / yes | point, then request fallback | validates UUID, tenant employee existence, and shared GIS assignment authorization; no physical employee FK is added |
| survey_date | date / yes | point, then request fallback | accepts only ISO `YYYY-MM-DD`; never defaults to today |
| name | varchar(30) / yes | point | trimmed string; defaults to `source_row_id` only when that value is at most 30 characters |
| code | varchar(30) / yes | point | trimmed string; defaults to `raw_code` only when that value is at most 30 characters |
| raw_x/raw_y/raw_z | numeric(20,3) / numeric(20,3) / numeric(10,3), all yes | point | source Easting/Northing/height preserved unchanged |
| x/y/z | numeric(20,3) / numeric(20,3) / numeric(10,3), all yes | do not derive separately | server copies the submitted raw values; current v1 has no client-only final-coordinate reinterpretation |
| longitude/latitude | double precision / yes | a complete pair may define input geometry | both non-null values take precedence over raw coordinates; the server has no separate range/finite validator and always overwrites both from normalized EPSG:4326 `geom` after insert/update |
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
`surveyed_at`, `survey_code`, `filter`, and `type` are not import fields in v1;
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
- The server assigns `source_id`, copies raw_x/y/z into x/y/z, constructs
  `raw_geom` and `geom`, then derives stored longitude/latitude from `geom`.
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
| B — legacy compatibility duplicate | x/y/z, raw_geom | x/y/z mirror imported raw ordinates; raw_geom currently mirrors normalized geom and is excluded from scalar QGIS form attributes |
| C — optional instrument input | solution_info, pdop, antenna_height, raw_data | validated optional GNSS/device metadata; `raw_data` is JSONB (`rawdata` is not a DB column) |
| D — meaning not established | survey_code, surveyed_at, filter, type, description | existing nullable legacy/reserved columns; import rejects these top-level point keys |

No field in class D is automatically populated or reinterpreted by this
contract. The duplicate class remains for compatibility and is not a proposal
to add or remove physical columns.

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

### Source deletion precheck and execute

Use the project-scoped item endpoint:

```http
GET /gis/projects/{project_id}/api/survey-sources/{source_id}/
DELETE /gis/projects/{project_id}/api/survey-sources/{source_id}/
```

GET requires `maps.view`. DELETE additionally requires project GIS write
access. Neither method accepts a request body. GET the item endpoint before
enabling a destructive action:

```json
{
  "ok":true,
  "project_id":"11111111-1111-4111-8111-111111111401",
  "delete":{
    "source_id":"30000000-0000-4000-8000-000000000002",
    "source_group_id":"30000000-0000-4000-8000-000000000002",
    "supersedes_id":null,"version":1,"is_active":true,"point_count":22,
    "links":{"LINKED":0,"MANUALLY_MODIFIED":0,"UNLINKED":0},
    "linked_target_count":0,"child_version_count":0,
    "shared_object_reference_count":0,"has_archived_object":true,
    "object_key_valid":true,"can_delete":true,"blocked_reason":null
  }
}
```

DELETE is allowed only for an independent, active version-1 source with no
parent/child version lineage, no shared object key, a valid scoped object key,
and no Survey-link row in **any** status. `UNLINKED` is retained audit history
and therefore blocks source deletion just like `LINKED` and
`MANUALLY_MODIFIED`. `linked_target_count` is the number of distinct
`(layer_id,target_id,vertex_index)` targets referenced by link rows. Facilities
are never deleted or edited.

The active/inactive policy is intentionally strict: an inactive source cannot
be deleted; any source whose `version` is not 1, has `supersedes_id`, or has a
child source is blocked as `version_lineage`. Deleting a source never deletes a
version chain and never reactivates a prior version.

On success, the DB transaction deletes every `gis.survey` row matching both
the URL project and `source_id`, then deletes exactly that `gis.survey_source`
row. It does not delete Survey points belonging to another source/project and
does not change any facility or `gis.survey_link` row (links already make the
precheck fail). One Survey delete revision/change-log event is written per
deleted point and a normal `changeset_receipt` is completed. With zero points,
`deleted_point_count` is 0, `first_revision` and `last_revision` are null, and
`current_revision` is unchanged.

The private S3 object is deleted only after the DB commit and only when
`original_file_key` is empty or begins with the exact
`tenants/{tenant}/gis/{project_id}/survey-sources/{source_id}/` prefix. A key
referenced by another source blocks deletion as `shared_object`; an out-of-scope
key blocks it as `invalid_object_key`.

```json
{"ok":true,"source_id":"30000000-0000-4000-8000-000000000002","deleted_source_id":"30000000-0000-4000-8000-000000000002","deleted_point_count":22,"deleted_object":true,"cleanup_pending":false,"first_revision":20,"last_revision":41,"current_revision":41}
```

The success response is HTTP 200. If there was no archived object,
`deleted_object` is true without an S3 request. If S3 cleanup fails after the
atomic DB delete, the response remains HTTP 200
with `deleted_object:false` and `cleanup_pending:true`; the receipt retains the
private cleanup key for an operator retry, but the HTTP response never exposes
that key. The server does not restore a deleted DB source after a storage-only
failure and never reactivates a previous source version.

Blocked deletion is HTTP 409:

```json
{"ok":false,"error":"survey_source_in_use","reason":"linked_survey_points","delete":{"can_delete":false,"blocked_reason":"linked_survey_points"}}
```

Stable reasons are `linked_survey_points`, `manually_modified_links`,
`unlinked_history`, `version_lineage`, `inactive_source`, `shared_object`, and
`invalid_object_key`. A missing source is HTTP 404
`{"ok":false,"error":"survey_source_not_found"}`. A DB failure is HTTP 503
`{"ok":false,"error":"survey_source_delete_failed"}` and is logged server-side
without exposing SQL, object keys, or credentials.

The precheck itself uses the same 404 `survey_source_not_found` response for a
missing/project-mismatched source. Invalid path UUIDs are rejected by Django URL
routing. Authentication and authorization failures use the shared Django
responses rather than a Survey-specific JSON error.

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

No GeoJSON/WKT `geom`, source version/group, or dedicated method is returned.
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
| 409 | `survey_source_in_use` | guarded source deletion is blocked |
| 404 | `survey_source_not_found` | project-scoped source missing |
| 409 | `survey_link_conflict` | mapping/referenced-object conflict |
| 503 | `survey_failed` | Survey DB unavailable |
| 503 | `survey_source_delete_failed` | guarded Source DB deletion failed and rolled back |
| 503 | `survey_link_unavailable` | Changeset receipt/runtime unavailable |
| 503 | `survey_link_failed` | Survey-link DB unavailable |

Source/Survey FKs use RESTRICT and cannot cascade into facilities. The guarded
Source item DELETE endpoint removes only an independent Source and its unlinked
Survey points after the explicit precheck above.

## 10. Earlier brief vs deployed contract

| Topic | Earlier implication | Deployed/final contract |
|---|---|---|
| Presign | URL names unspecified | `presigned_url`, `object_key`, `headers`; PUT; 900 s |
| File import | server might parse file | server verifies file; client supplies parsed `points` |
| Working CRS | project scope might supply it | no lookup; client sends EPSG, server transforms once |
| Point cap | 5,000 cap | silent LIMIT; no count/total/truncated/pagination |
| Worker/date/method | requested metadata | worker/date plus selected GNSS fields mapped; unknown method stays in `raw_data` |
| Source delete | no endpoint | guarded GET precheck + DELETE; any link/version history blocks |
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
