# GeoFlow GIS Survey lineage contract v1

Status: server/tenant contract. QGIS Connector and QField UI are out of scope.

## Ownership and coordinate rules

- `gis.survey_source`, `gis.survey`, and `gis.survey_link` live in each tenant DB.
- Central `gis.definition_layer.id` is stored logically in `survey_link.layer_id`; no cross-DB FK is created.
- Facility rows keep their existing UUID `id`; no `survey_id` column is added to facility tables.
- `raw_x/raw_y/raw_z/raw_crs` preserve source coordinates. `geom` and `raw_geom` are always Point EPSG:4326.
- Source files remain private object-storage objects. The DB stores `original_file_key`, never file bytes or a presigned URL.

## Tables

### `gis.survey_source`

| Field | Type | Null | Meaning |
|---|---|---:|---|
| id | uuid PK | no | immutable source version ID |
| project_id | uuid | no | tenant project |
| source_group_id | uuid | no | stable lineage/series ID |
| supersedes_id | uuid FK | yes | prior source version |
| source_type | varchar(20) | no | `GNSS`, `GPS`, `TOTAL`, `CSV`, `XLSX`, `OTHER` |
| original_file_name | text | no | display/audit name |
| original_file_key | text | yes | private storage reference |
| imported_at/imported_by | timestamptz/uuid | no/yes | import audit |
| source_crs | text | yes | normally `EPSG:n` |
| geoid_model | text | yes | geoid identifier |
| calibration_info | jsonb object | no | calibration metadata |
| version | integer | no | positive version inside group |
| is_active | boolean | no | one active version per group/project |
| note | text | no | operator note |

Sources are never overwritten or cascaded away. A revision inserts a new row, deactivates the prior active version, and retains the same `source_group_id`.

### `gis.survey` additions

`source_id uuid`, `source_row_id text`, `raw_crs text`, `raw_code text`, and `raw_geoid_model text` are added. Existing raw/final fields are reused. During a source revision, `(project, source_group_id, source_row_id)` finds an existing logical point; its Survey UUID is retained while coordinates and `source_id` advance to the new version.

### `gis.survey_link` additions

| Field | Type | Null | Values/meaning |
|---|---|---:|---|
| vertex_index | integer | yes | zero-based LineString vertex; null for point links |
| link_role | varchar(20) | no | `POINT`, `VERTEX` |
| link_status | varchar(30) | no | `LINKED`, `MANUALLY_MODIFIED`, `UNLINKED` |
| created_by | uuid | yes | creator |
| updated_at/updated_by | timestamptz/uuid | no/yes | latest state audit |

`POINT` requires a Point target and null `vertex_index`. `VERTEX` requires a LineString target and a non-negative in-range index. There is one active mapping per `(layer_id, target_id, vertex position)`. An unlinked historical row does not block a later mapping.

PostGIS geometry has no stable per-vertex UUID. Contract v1 therefore uses `vertex_index`. A client that inserts or removes a vertex must submit mapping `update` changes that remap all affected indexes in the same logical edit. Until that occurs, reapply rejects an out-of-range mapping; it never guesses.

## APIs

All paths are project-scoped, session authenticated, tenant resolved fail-closed, and require `maps.view`; writes additionally require project GIS write access.

### List/import/revise sources

`GET /gis/projects/{project_id}/api/survey-sources/?include_inactive=1`

`POST /gis/projects/{project_id}/api/survey-sources/`

The same POST creates v1 or a later version. For a later version send the prior `source_group_id` and `supersedes_id`.
First request `{"action":"presign","id":"...","original_file_name":"survey.csv","mime_type":"text/csv"}`.
The returned private tenant/project-scoped object key is uploaded with the supplied URL. The import request may then send that key; the server verifies object existence and encryption before accepting it. Presigned URLs are never stored.

```json
{
  "id": "30000000-0000-4000-8000-000000000002",
  "source_group_id": "30000000-0000-4000-8000-000000000001",
  "supersedes_id": "30000000-0000-4000-8000-000000000000",
  "source_type": "TOTAL",
  "original_file_name": "survey-v2.csv",
  "original_file_key": "gis-survey/tenant/project/source-v2.csv",
  "source_crs": "EPSG:5186",
  "geoid_model": "KNGeoid18",
  "calibration_info": {"control_set": "2026-10"},
  "points": [
    {"source_row_id": "P001", "raw_x": 200000.12, "raw_y": 500000.34, "raw_z": 12.3},
    {"source_row_id": "P002", "longitude": 127.123, "latitude": 36.456, "raw_z": 12.1}
  ]
}
```

Response includes `source_id`, `source_group_id`, `version`, point create/update counts, and project revision range. Source row IDs must be unique inside a submitted source. A revision preserves matching Survey UUIDs.

### List Survey points

`GET /gis/projects/{project_id}/api/survey-points/?source_id={uuid}`

Returns source identity, raw coordinates/CRS/code/geoid, final x/y/z and EPSG:4326 longitude/latitude. The response is capped at 5,000 points; bulk import is a separate staging concern.

### List mappings

`GET /gis/projects/{project_id}/api/survey-links/?survey_id=&layer=&target_id=&include_unlinked=1`

Existing fields remain. New fields are `vertex_index`, `link_role`, `link_status`, `updated_at`, and `updated_by`.
Unlinked history is excluded unless `include_unlinked=1` is requested, preserving the old active-link list behavior.

### Create/update/unlink mapping

`POST /gis/projects/{project_id}/api/survey-link-changesets/`

```json
{
  "client_id": "40000000-0000-4000-8000-000000000001",
  "changeset_id": "40000000-0000-4000-8000-000000000002",
  "base_revision": 17,
  "changes": [
    {
      "action": "create",
      "id": "40000000-0000-4000-8000-000000000003",
      "survey_id": "50000000-0000-4000-8000-000000000001",
      "layer": "WTL_VALV_PS",
      "target_id": "60000000-0000-4000-8000-000000000001",
      "match_method": "manual",
      "link_role": "POINT",
      "link_status": "LINKED"
    },
    {
      "action": "create",
      "id": "40000000-0000-4000-8000-000000000004",
      "survey_id": "50000000-0000-4000-8000-000000000002",
      "layer": "WTL_PIPE_LM",
      "target_id": "60000000-0000-4000-8000-000000000002",
      "match_method": "manual",
      "link_role": "VERTEX",
      "vertex_index": 1
    }
  ]
}
```

State transition example:

```json
{"action":"update","id":"40000000-0000-4000-8000-000000000004","link_status":"MANUALLY_MODIFIED"}
```

Explicit disconnect preserving history:

```json
{"action":"unlink","id":"40000000-0000-4000-8000-000000000004"}
```

Legacy `delete` remains supported for backward compatibility, but new clients use `unlink`. `KEEP_LINK` means update/retain `LINKED`; `MARK_MANUAL` maps to `MANUALLY_MODIFIED`; `UNLINK` maps to the unlink action.

### Reapply preview

`POST /gis/projects/{project_id}/api/survey-reapply-preview/`

```json
{"source_id":"30000000-0000-4000-8000-000000000002"}
```

Alternatively send `survey_ids`; optionally restrict either request with `mapping_ids`. The response classifies every mapping as `applicable`, `manually_modified`, `unlinked`, or `invalid`, with counts and IDs. Preview makes no mutation.

### Reapply execute

`POST /gis/projects/{project_id}/api/survey-reapply/`

Request selection is identical to preview and may include `client_id`/`changeset_id`. Only `LINKED` mappings apply. A point target receives the Survey point. A LineString receives `ST_SetPoint` at the mapped index. The server checks project ownership, current Layer Plan, geometry type, vertex range, Survey geometry, and result validity. Every changed feature receives a project revision and geometry before/after audit record.

## Errors

| HTTP | Code | Meaning |
|---:|---|---|
| 400 | `survey_rejected` | invalid type, CRS/input, role/status, vertex, geometry, or selection |
| 400 | `survey_link_rejected` | invalid mapping changeset |
| 403 | Django permission response | tenant/project/write access denied |
| 409 | `survey_conflict` | source/mapping/target conflict |
| 409 | `survey_link_conflict` | relation UUID, active target position, or referenced object conflict |
| 503 | `survey_failed` / `survey_link_failed` | tenant database operation unavailable |

Survey or source deletion must not cascade into facilities. Existing feature/survey deletion guards remain; source and Survey source FKs use `RESTRICT`.
