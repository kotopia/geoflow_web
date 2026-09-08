# GeoFlow GIS common foundation closeout

Status: implementation complete; release and production activation are separate gates.

## Delivered common contract

- project-scoped Snapshot, Changeset, Delta, idempotency receipts and revisions;
- create/update/delete with server-side Layer Plan, field, UUID, geometry and
  project authorization checks;
- explicit QField delete capture with offline retention and rollback reconciliation;
- delete protection for surveys/facilities that still have lineage links;
- `survey_link_changeset_v1` create/unlink contract and project-scoped query API;
- relation events in the project Delta stream using `resource_kind=relation`;
- WebGIS feature create/update/delete partial refresh and project event metadata;
- exact physical tenant DB allow-list for any non-development GIS pilot runtime.

## Runtime gates

Development remains enabled only when all existing strict-dev conditions pass.
Non-development GIS sync remains disabled unless both variables are present in
the host-owned environment:

```text
GEOFLOW_GIS_PILOT_ENABLED=1
GEOFLOW_GIS_PILOT_DATABASES=<exact physical pilot tenant DB name>
```

The global switch alone does not enable any database. A database must match the
comma-separated allow-list exactly, case-insensitively. The values must never be
committed to Git.

Realtime WebSocket delivery remains development-only until the production ASGI
and shared channel layer rollout is separately reviewed. Persistence and client
recovery do not depend on WebSocket delivery; Snapshot/Delta remain authoritative.

## Production activation boundary

Merging and deploying the application code does not mutate a production tenant
database and does not activate GIS sync. Production activation additionally
requires all of the following for one explicitly selected pilot tenant:

1. backup and read-only schema inventory;
2. reviewed GIS DDL rehearsal against a disposable clone;
3. explicit approval for the exact tenant DB schema mutation;
4. GIS foundation, feature, metadata/profile, capability and revision tables;
5. one pilot project/profile assignment;
6. the two fail-closed runtime variables above;
7. authenticated read smoke before write activation;
8. create/update/delete/link/unlink/Delta smoke with disposable pilot objects;
9. rollback by disabling the runtime switch first; data/schema rollback is a
   separately reviewed operation and is never automatic.

## Client implementation boundary

The common server contract is complete without implementing the final QGIS or
QField survey-link selection screen. QGIS plugin stabilization is the next
product phase. Field GNSS, photos and mobile-specific forms follow after the QGIS
workflow and metadata rules are stable.
