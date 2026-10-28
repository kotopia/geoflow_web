# GeoFlow Survey Source / Observation Contract

Status: implemented removal of persistent target matching, production migration pending.
Updated: 2026-10-20. This replaces the former observation-to-asset mapping contract.
Historical import baseline: `4c5fc553339bdf429b8ec5c6d656a414be484f6d`.

## Ownership and independence

Tenant `gis.survey_source` owns versioned original file metadata; `gis.survey`
owns observations and raw/final coordinates. GIS assets, including WTL_PIPE_PS,
are independent features. No server target matching model, API, bulk API,
reapply preview/execute, target role, delete guard, detach or cascade remains.
The Connector uses project-scoped spatial queries to find creation status,
duplicates and depth candidates. Survey numbers/codes are ordinary attributes.
Central definitions still own layer/field/form metadata and package selection.

## Session APIs and authorization

All routes require a signed-in tenant identity, maps.view, an accessible project
and active Final Layer Plan. Writes require existing project GIS write access.
Worker IDs use shared assignment authorization. No permission/revision/schema
validation is relaxed by the target retirement.

| Method | Route | Purpose |
| --- | --- | --- |
| GET/POST | /gis/projects/{project_id}/api/survey-sources/ | List, presign, finalize import |
| GET/DELETE | /gis/projects/{project_id}/api/survey-sources/{source_id}/ | Delete precheck / soft delete |
| GET | /gis/projects/{project_id}/api/survey-points/ | Optional source_id filter |
| GET/DELETE | /gis/projects/{project_id}/api/survey-points/{survey_id}/ | Precheck / soft delete |
| POST | /gis/projects/{project_id}/api/survey-points/bulk-delete/ | action precheck or delete |

DELETE /gis/projects/{project_id}/api/survey-sources/{source_id}/ requires
`mode=source_and_points&deletion_policy=source_and_points_soft_delete_v1`.
The approved Source + Point soft-delete policy is unchanged. The former
mode=source_only alias now returns 409 without mutation: old Connector builds
incorrectly promised preservation. Precheck and successful DELETE advertise
`deletion_policy=source_and_points_soft_delete_v1`; clients must stop before
DELETE if that explicit contract is absent. No compatibility route is retained for the
removed target matching or reapply APIs, including their device routes.

## Private original upload

POST action=presign with id/original_file_name/mime_type. Response includes
"presigned_url", "object_key", required headers and expiry (900 seconds).
The method is always `PUT`; honor the exact signed headers. Supported import
file types include CSV, application/vnd.ms-excel and XLSX. Successful S3 PUT can
return HTTP 200 with an empty response body. Finalize sends the private object
key plus parsed points; the server checks prefix, object length and encryption.
An invalid object returns "survey_source_object_invalid". Never log signed URLs
or object keys. File parsing remains the caller's responsibility.

## Source / point import

Source fields: id, source_group_id, supersedes_id, source_type,
original_file_name/key, source_crs, geoid_model, calibration_info, note,
optional survey_type and target_crs, worker_id, survey_date, points.
source_type remains GNSS/GPS/TOTAL/CSV/XLSX/OTHER (historically mixes method and
file format). Explicit survey_type separates method from source classification.
Each point requires unique source_row_id, optionally id, raw_x/raw_y/raw_z,
raw_crs/raw_code/raw_geoid_model, longitude/latitude, raw_data, worker_id,
survey_date, name, code, solution_info, pdop, antenna_height.
Point-level values override request-level worker/date defaults. Raw_data must be
an object. Dates use YYYY-MM-DD; finite numeric validation preserves NULL and 0.

### Client-supplied versus server-generated point values

survey_no/type/x/y/z are server-generated and rejected as client point inputs.
Raw coordinates remain original; projected raw x/y become final Easting/Northing.
Geographic input uses explicit projected target_crs, projected source_crs, or one
unambiguous project Source CRS; no guessed TM zone. geom is EPSG:4326;
longitude/latitude follow it. z preserves raw height without an invented zero.
Method domain is GNSS/TOTAL_STATION, unknown stays NULL. Number is YYMMDD-NNN
per project/date; project row lock and UNIQUE(project_id,survey_no) prevent
collisions. Source revisions preserve logical point UUID/number. Deleted numbers
are not reused. Missing date stays NULL. Import response includes final values.
Point reads return at most 5,000 rows ordered by source_row_id,id.

## Current inventory and inspection (1.4.4 candidate, not deployed)

Source lists accept `include_deleted=1` (with `include_inactive=1`) and return
`source_inventory_version=1`, `deleted_at`, `delete_reason`, active `point_count`
and `deleted_point_count`. These reuse existing Source/Survey audit columns;
no schema/backfill or persistent target relation is added. The default still
excludes deleted sources. Archived storage keys are never copied into UI diagnostics.

Point lists accept `source_state=retained` for active observations whose source
is deleted or unavailable, independently of PC settings. Responses include
`original_file_name`, `source_state` (active/deleted/unknown), `geometry_crs`,
and `current_crs` where the existing import contract establishes it. Project
scope applies to the source join. A 5,001-row probe returns at most 5,000 and
explicit `truncated`; the Connector warns that counts/extents are incomplete.
Old servers without that marker are incomplete at exactly 5,000. Failed or
malformed reads are errors, never zero counts or permission to clear history.

The Connector separates original files, nonempty retained observations and
Source deletion history. Historical QSettings IDs are diagnostic evidence only;
they cannot hide active sources or manufacture retained observations. On older
servers, a missing source is labelled deleted/unknown, not proven deleted.
Current x/y/z never fall back to raw_x/y/z. Details distinguish survey_no from
source_row_id, expose UUID copy, raw/current CRS and location availability.
Raw CRS does not automatically establish final-coordinate CRS. Canonical
EPSG:4326 geometry-derived longitude/latitude remains suitable for navigation.

Canvas navigation transforms into canvas CRS, uses a minimum extent and timed
rubber bands. It does not select a managed feature, switch layers, change
creation checks, load a form, save, or persist geometry. Duplicate inspection
uses unchanged spatial radius/target-code criteria and resolves GIS peers by
layer ID + object UUID, never table position/FID. It adds no Survey↔GIS relation.

The separate L2 omission is fixed in the reference response by resolving central
active catalog labels from the existing project Final Layer Plan capabilities.
It does not infer business scope from Survey sources or modify project scope.

## Deletion

Source/Point deletes keep their existing soft-delete/audit/Delta/receipt and
S3 cleanup policy. Target counts, protections, relation cascades and unlink
operations have been removed from precheck and responses. No GIS asset is read,
updated or deleted by observation deletion. Facilities_deleted remains 0.
Deleted observations are excluded from read APIs and materialized packages.
Source cleanup honors shared-object references and tenant/project prefixes.
Cleanup outcome includes "cleanup_pending":false on success; failed cleanup is
recorded for retry. Errors remain survey_source_delete_failed and
survey_point_delete_failed with existing 404/400/409/503 semantics for actual
source/point state, invalid input, conflict and infrastructure failure.

## Changesets / Delta / packages

General GIS CREATE/UPDATE/DELETE no longer reads or writes matching relations.
Permissions, tenant/project isolation, real revision conflicts, idempotency and
schema checks remain authoritative. Survey attributes (survey_no, code, raw_code,
x/y/z, longitude/latitude, worker/date) remain available through normal import,
reads, Delta and definition-driven GeoPackage materialization. Raw_code is
included in package output when selected by the central definition.
All Delta records are features. Old relation-only audit/receipt rows are retired
by migration; historical reapply entries keep geometry/audit but lose target
provenance keys. Revision numbers are not renumbered or reduced. Delta next_revision
advances to current_revision on the final page even across retired-event gaps.
Manifests expose no matching or reapply transport keys. Existing packages contain
only configured spatial features and standard package metadata.

## Migration and recovery

0047_remove_survey_targets drops only the SQL-managed retired relation table,
without CASCADE; its indexes/constraints/outgoing FK disappear with the table.
There was no Django model/admin registration. Published migration 0044 remains
immutable; references required for historical replay/reversal remain only in
migration/recovery code. A literal zero in migration history would prevent safe
replay/reversal; active model/service/API/manifest references are removed.
Foundation/demo bootstrap no longer creates a matching relation.

The deployment command requires --apply and --backup-dir, active tenant
configuration and applied 0046. With service stopped, it locks GIS tables,
writes private 0700/0600 recovery files, then compares counts/SHA256 fingerprints
of every unrelated GIS table, including complete Survey/Source/asset geometry
and attributes. Unexpected inbound dependencies fail without CASCADE. It applies
and records the exact migration transactionally per tenant and validates absence.
A retry preserves the original backup. --check is read-only and detects a
partially completed prior run. No backup contents are published in Actions.

Django reverse migration recreates the old schema. To restore relation/audit
rows as well, stop service, use deploy_gis_survey_target_removal --apply --restore
--backup-dir <the original private backup directory>, then deploy the compatible
previous code before restart. Recovery rejects changed unrelated GIS state.
Per-tenant commits are explicit: failure does not undo already committed tenants.
The workflow restarts compatible current code on failure and requires reviewed
recovery for any reversal. Never check out old code against a retired table.

## Verification and prior final-field release

Previous successful deployment38987668773 applied final fields to all3 tenants.
Backfill examined389 points:367 numbers,32 known methods,22 latitude/longitude
pairs; second pass changed0. Unknown dates22/methods357 stayedNULL. Production
import of 22 mixed EPSG:4326/EPSG:5186 points +3 TOTAL_STATION, Delta25 and
GeoPackage25 passed. This raw/final contract is retained by the retirement.

Retirement tests cover forward/reverse/recovery, unrelated-data fingerprints,
Source/Point/facility independence, ordinary CRUD without target SQL, missing
matching routes and transport metadata, Delta revision gaps and package fields.
Production completion requires the protected run, absence of the retired table,
unchanged Survey/Source/assets, login200, project runtime/package and CRUD smoke.

### Empty-tenant deployment recovery (2026-10-20)

Protected run39375348490 passed approval but stopped before its first target DDL:
the backup queried optional sync audit tables absent in an empty foundation-only
tenant. No target retirement completion was logged; the failure handler restarted
the service successfully. Backups now inspect actual relation existence and treat
absent optional audit stores as zero records. Existing stores must still be fully
read and validated; errors are never swallowed. Stage-only diagnostics contain no
business records or credentials. A disposable PostGIS test drops both optional
audit tables and verifies forward/retry/recovery with unchanged unrelated data.
Migration0047 is unchanged. The protected retry remains required for production
removal counts, preservation fingerprints and actual API/package smoke.
