# GeoFlow GIS Sync Architecture v1

Status: **approved product/technical direction**

This document freezes the GeoFlow GIS synchronization model agreed for QGIS, QField, WebGIS, and PostGIS. It replaces whole-GeoPackage upload/diff as the normal operating model. The existing whole-package sync remains a development/fallback path until the v1 client transition is complete.

## 1. Authority and transport roles

- PostgreSQL/PostGIS is the authoritative Source of Truth.
- QGIS and QField edit local data; they do not receive tenant-wide database credentials.
- Changeset API is the authoritative write path.
- WebSocket is the live change-notification path, not the persistence path.
- Snapshot is the bulk/bootstrap read path.
- Delta is the incremental read path after a client has a valid local baseline.

Normal flow:

`QGIS/QField local edit -> Changeset API -> PostGIS transaction -> project revision -> WebSocket event -> interested clients apply/fetch the changed feature`

## 2. Changeset semantics

A Changeset contains only objects that changed locally. Updates contain only fields actually changed by the client; geometry is included only when geometry changed.

Required identity/safety rules:

- object `id` is the authoritative UUID and immutable after creation;
- `project_id` is server-scoped and immutable from the client;
- Layer Plan/profile determines which layers and fields are writable;
- create with an existing UUID is rejected;
- update of a server-missing object is rejected as a deleted/missing conflict;
- geometry is validated server-side/PostGIS-side;
- one Changeset is atomic;
- each Changeset has a client-generated `changeset_id` and `client_id` for idempotent retry.

Concurrency policy:

- different objects never overwrite each other;
- different fields on the same object merge naturally because updates are field patches;
- the same field changed by multiple clients uses **last successful server write wins**;
- geometry changes on the same object use **last successful server write wins**;
- history/audit retains the overwritten state so last-write-wins does not erase traceability.

## 3. Project revision and Delta

Each GIS-enabled project has a monotonically increasing `current_revision`.

Each committed object change consumes one project-local revision. A multi-object Changeset therefore receives a contiguous revision range inside the same database transaction.

Each client stores `last_applied_revision`, defined as the last **contiguous** server revision successfully applied to its local cache. A client must never advance this cursor past a missing/unapplied revision.

Delta read:

`GET project delta since last_applied_revision -> ordered changes -> apply locally -> advance cursor`

A QGIS worker does not need to re-download changes it already applied/acknowledged. If worker A created 500 changes and worker B created 400 changes, A normally pulls only B's unapplied changes and B pulls only A's unapplied changes; WebSocket delivery may reduce the next pull further.

If a local baseline no longer exists, or the requested revision is older than retained Delta history, the client downloads a new Snapshot and resumes Delta from that snapshot revision.

## 4. QGIS read/cache model

QGIS uses **Full Project Snapshot + Incremental Delta**.

- First open on a device: download one project GeoPackage snapshot.
- Frequent pan/zoom remains local and must not depend on viewport network requests.
- Subsequent opens: retain the local package and apply server Delta only.
- Snapshot GeoPackage layers use RTree spatial indexes.
- QGIS display performance is controlled by spatial index plus scale-dependent rendering/labels, not by re-fetching the viewport on every pan.

Local cache policy defaults (settings, not hard-coded product constants):

- active project unused for 90 days: eligible for local cache cleanup;
- completed project: eligible for cleanup after a 30-day grace period;
- `dirty`/pending-sync data: never auto-delete;
- pinned project: never auto-delete;
- device cache quota may evict eligible projects by LRU, preferring completed/old projects first.

If the local package was evicted, reopen by downloading the newest Snapshot, then apply any Delta after its snapshot revision.

## 5. QField read/cache model

QField uses **GPS + viewport driven roaming cache**, not a manually drawn AOI by default.

Initial center priority:

1. current GPS when the worker is near the project;
2. last field-work location for the project;
3. project representative/center location;
4. user chooses an initial map location when none of the above exists.

Cache behavior:

- active radius loads data needed for current work;
- a larger prefetch radius loads the next surrounding ring in the background;
- movement past a threshold loads only newly uncovered grid/tile cells;
- map panning outside the cached area also loads only newly required cells;
- recently visited cells remain warm/local and are evicted by LRU only when policy/storage requires it;
- dirty/pending-sync objects are never evicted;
- QField remains offline-first: local editing continues without WebSocket/network and queued Changesets are sent when connectivity returns.

The exact active radius, prefetch radius, grid size, retention, and storage quota are configurable.

## 6. WebGIS read/update model

WebGIS does not download a full project dataset into the browser.

- Read path: viewport/BBOX and/or vector tiles.
- After a committed Changeset, WebSocket emits project/layer/object/action/revision metadata.
- WebGIS refreshes/replaces only the affected feature (or the minimum affected tile), not the whole page or all layers.

## 7. WebSocket role

WebSocket announces committed server changes. It must not bypass the Changeset API or server authorization.

Minimal event identity:

- project_id
- revision
- layer / standard_name
- object_id
- action (`create`, `update`, `delete`)

A client may ignore events outside its current project/cache. QField should not be forced to download changes for distant, uncached areas.

## 8. New project behavior and spatial indexes

A new project may have zero GIS objects. The approved Layer Plan still materializes empty local layers.

PostGIS spatial indexes are created with the physical GIS tables, including while empty. PostgreSQL maintains GiST indexes automatically on INSERT/UPDATE/DELETE; indexes are not rebuilt for every object.

GeoPackage RTree indexes are created with local feature layers and maintained as local objects are inserted/updated/deleted.

The project spatial extent may start empty. The first geometry establishes an extent; later creates can expand it incrementally. Expensive full `ST_Extent` recalculation is reserved for cases such as deletion/change of a boundary-defining object.

## 9. Bulk import is separate from interactive sync

Large existing-dataset imports (hundreds of thousands/millions of objects) use a staging/bulk-load path rather than thousands of interactive Changeset requests:

`staging -> COPY/bulk load -> validation -> authoritative tables -> index/ANALYZE -> snapshot`

After the initial import, normal user editing uses Changesets/Delta.

## 10. Audit/history

Last-write-wins is acceptable only with durable server history. Each committed object revision records enough information to identify and restore the change:

- project revision;
- layer/object/action;
- changed field names;
- old/new attribute values for the patch;
- geometry before/after when geometry changed;
- changeset/client identity;
- actor reference when available;
- timestamp.

## 11. Transition from the current MVP

Current MVP behavior uploads a complete GeoPackage and computes a server-side diff. It has proven project authorization, editable local GeoPackage operation, save-triggered sync, and PostGIS persistence, but it is not the final high-volume transport.

Transition order:

1. add project revision/change-log/idempotency support;
2. add Changeset write API and Delta read API;
3. expose protocol/revision endpoints in the QGIS manifest;
4. change QGIS save-sync from full-package upload to local Changeset extraction;
5. add local Delta application and retained project snapshots;
6. add WebSocket project events and partial WebGIS refresh;
7. implement QField roaming cache/offline queue;
8. enforce cache lifecycle and snapshot retention policy;
9. keep whole-package sync only as a gated fallback/import diagnostic path.

No production schema/data mutation, production migration, or production deployment is authorized by this architecture document.