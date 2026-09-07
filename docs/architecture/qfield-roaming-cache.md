# GeoFlow QField Roaming Cache v0.1

Status: server contract foundation implemented; mobile QField plugin/package integration pending.

## Goal

QField must not require a user to draw a manual AOI before fieldwork. GeoFlow chooses local cache cells automatically from the device position and current viewport, while PostGIS remains the sole Source of Truth.

## Initial center priority

The QField client should resolve its initial map/cache center in this order:

1. current GPS position;
2. last known GeoFlow project location stored on the device;
3. project center supplied/materialized by GeoFlow;
4. current map viewport as the final fallback.

The server roaming-plan API accepts GPS and/or viewport input. Client-side fallback resolution is part of the QField plugin/package step.

## Grid

The roaming grid is metric and stable. Cell indices are calculated in Web Mercator meters and cell bounds are transported as EPSG:4326 bboxes.

Initial defaults:

- cell size: 250 m;
- active radius: 300 m;
- prefetch radius: 750 m;
- movement threshold before replanning: 100 m;
- maximum cells returned by one plan: 192.

These are protocol defaults, not hard-coded business rules. The client may request different values within server safety bounds.

Cell key format:

`cell_size_m:ix:iy`

## Priority

Cells are ordered as:

1. `active`: intersects the GPS active radius;
2. `viewport`: intersects the current map viewport and is not already active;
3. `prefetch`: intersects the outer GPS prefetch radius.

The client sends its known cell keys. The server returns only missing cells, which prevents repeated downloads while the user remains in the same area.

## API

### Roaming plan

`GET /gis/projects/<project_uuid>/api/qfield/roaming-plan/`

Inputs:

- `lon`, `lat` (paired, optional when viewport exists)
- `viewport=minx,miny,maxx,maxy`
- `known=<cell>,<cell>,...`
- `cell_size_m`
- `active_radius_m`
- `prefetch_radius_m`
- `max_cells`

Response includes:

- project/current revision;
- permitted GIS layer list from Layer Plan/Profile;
- new cells ordered by priority;
- each cell bbox and fetch URL;
- Delta and Changeset URLs;
- eviction invariants.

### Roaming cell

`GET /gis/projects/<project_uuid>/api/qfield/roaming-cell/?cell=<cell_key>`

Optional:

- `layers=WTL_PIPE_LM,DORO,...`
- `limit_per_layer` (default 1000, max 5000)

The response is grouped by enabled profile layer and contains GeoJSON geometry plus all materialized profile attributes. `truncated=true` is explicit when a dense layer exceeds the per-cell limit; the client must not treat a truncated cell as complete.

## Local cache rules

QField will maintain a small local GeoPackage using the same UUID identity, profile fields, Changeset and Delta semantics as QGIS.

Eviction rules are mandatory:

- dirty cells are never evicted;
- pending/outbox cells are never evicted;
- pinned project data is never automatically evicted;
- clean cells use LRU when device cache limits are reached;
- movement downloads only cells not already cached.

## Sync

Field edits continue to use the existing GeoFlow Changeset protocol. Server WebSocket events are hints only; authoritative state is received through Delta. Offline changes remain local until network is available and must survive application restarts.

## Remaining implementation

1. QField app/project plugin authentication and project selection.
2. QField package materialization (`.qgs/.qgz`, local GeoPackage, project QML sidecar).
3. GPS + viewport listeners using QField `iface.positioning()` and `iface.mapCanvas()`.
4. Roaming-plan scheduler using the 100 m movement threshold and viewport changes.
5. Cell response application into local GeoPackage layers, preserving dirty rows.
6. Per-cell LRU index and storage quota.
7. Offline Changeset/outbox retry and Delta application on reconnect.
8. Dense-cell pagination/subdivision handling when `truncated=true`.
9. Device PoC on Android/iOS followed by field GNSS/NTRIP validation.

QField provides a QML/JavaScript plugin framework with project and app-wide plugins, so GeoFlow can implement this without a separate native fork of QField. The plugin must remain thin; authorization and business rules stay on GeoFlow Server.
