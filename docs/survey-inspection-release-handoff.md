# Survey inspection / deletion contract handoff — 2026-10-27

## Basis and observed discrepancy

Release and production `geoflow-stabilized` were both at
`87132c5c57bfebf14ae4335c0748c241f1a85b77` (release HEAD rechecked before PR).
Installed Connector metadata says 1.4.3, but installed runtime includes unmerged
PR #431 changes and is not the immutable 1.4.3 package. That PR's metric overlap
diagnostics are incorporated here without changing the collision radius or target
criteria; it should be reconciled before merging it separately.

The approved architecture contract and commit
`21d2f3f708443fe54a443275bbdd8e2d1133c35d` (PR #397) specify Source + Point soft
deletion, independent of GIS assets. Production still accepts `source_only` as
an alias, whereas the installed UI promises point preservation and records local
retention history. This is a destructive semantic mismatch, not a new deletion
policy decision. No production DELETE was used in this investigation.

The affected project's local label counted two historical Source IDs, not points.
Both IDs refer to diagnostic CSV sources; their persisted deletion receipts each
report zero points and zero facilities deleted. Server inventory contains one
active Source with 53 active points, six deleted Sources (one with 53 soft-deleted
points, five with zero current points), and zero active source-less/deleted-source
points. Snapshot and server active UUID sets are equal (53). These facts do not
prove preservation of every historically imported point. The remembered prior
count of three has no corroborating settings snapshot: its time/cause/actor remain
unknown. Private project UUID/row audit evidence stays outside Git.

## Changes and compatibility

- Server exposes deleted-source inventory, active/deleted counts, source/CRS
  provenance and a retained filter. The 5001st row detects a 5000-row truncation;
  clients display an explicit incomplete-result warning rather than claiming a
  complete Source extent/count.
- DELETE requires `source_and_points` and explicit
  `source_and_points_soft_delete_v1` acknowledgement. Legacy preservation requests
  are rejected before mutation. Existing service soft-delete/asset independence
  remains unchanged. Client requires the policy in precheck, verifies response
  counters and reads the inventory again; older servers fail closed.
- Server state drives retained rows across profiles; old QSettings IDs are read
  only as historical evidence. Empty retained rows disappear, errors remain
  errors, and deletion history is shown separately. Obsolete retention writers
  have been removed without erasing existing settings.
- Survey detail separates survey number, original row identifier, UUID, current
  and raw coordinates/CRS. Navigation uses canonical geometry or current
  coordinates with explicit CRS, preserves zero, and never substitutes raw values.
- Temporary canvas highlights support selection, double click, multiple points,
  whole Source, and duplicate pairs. GIS counterparts use layer ID + object UUID.
  Navigation does not select an active layer, save edits, alter creation checks,
  or create persistent Survey/GIS links.
- L2 is a separate response omission: project Final Layer Plan has two selected
  L2s, but production catalog response omits `business_types`, which the existing
  parser expects. The catalog response now resolves active central L2 labels from
  the existing plan scope. No Survey-based scope inference is introduced.

## Validation evidence

- DB-free GIS suite: 248 tests, 12 dependency-related skips.
- Disposable localhost PostGIS: 20 tests, including real retained query SQL,
  Source deletion, facility preservation and Delta behavior.
- QGIS 4.2.2 offscreen: popup 43, creation 25, inspection 5 tests pass.
- Actual running QGIS: one active CSV / 53 points / no empty retained entry;
  single 1, multiple 2, whole Source 53 temporary highlights. Layer state, active
  layer, creation checks and dirty form identity unchanged; read-only wrapper
  permitted GET only, with zero survey-links calls.
- Actual duplicate list: three batch pairs (1.068, 1.746, 1.477 m) and one existing
  GIS counterpart (0 m), unchanged 2 m radius. Existing-GIS pair navigation drew
  both highlights. Isolated QGIS test exercises both pair types after sorting.
- NULL/zero/geometry-only coordinates, EPSG:4326→5186 canvas conversion, UUID
  selection after sort, failed-vs-empty lookup and profile-independent retained
  lookup are covered by QGIS regression tests.
- Immutable 1.4.3 bytes are reconstructed from archived changed files plus original
  inventory; original ZIP SHA, 5,221,008-byte size and 5,600-file checks remain exact.
  LF/CRLF reconstruction is accepted only if the original per-file SHA and size
  match. Tampered bytes still fail. 1.4.4 has a separate manifest and archive.

## Release and remaining operational verification

Candidate 1.4.4 SHA-256:
`ae80feb7070215b601eb352ffd5637f8b8378af04f4cf1ad3eaa194021713957`
(5,226,447 bytes / 5,601 runtime files). Original 1.4.3 SHA-256 remains
`8576b07bedd7649d45be3bdcebd2ae8cba84d0327d2eef29ed5676ffd883aac5`.
Neither package publication nor production deployment was performed.

The follow-up production promotion pins the above 1.4.4 size/hash and source
commit in `docs/operations/qgis-plugin-stable-release.json`. The protected GIS
deployment runs `smoke_qgis_project_runtime --survey-inspection` under read-only
database settings before publishing: it exercises scoped L2 catalog serialization,
Source inventory including deleted rows, and every active Source's deletion
precheck contract/count. This does not invoke DELETE or claim an authenticated
external HTTP session. Deployment path validation explicitly admits this handoff
and the changed GIS reference view; unrelated paths remain rejected.

Stable promotion keeps the old 1.4.3 package and archives its index for rollback,
then verifies the new public XML/ZIP and unchanged test index. Public stable URL:
`https://geoflow.co.kr/gis/qgis/plugins/plugins.xml`; package URL:
`https://geoflow.co.kr/gis/qgis/plugins/packages/geoflow_connector-1.4.4.zip`.
Changing the stable index back to the recorded previous index restores the old
download. Server rollback also restores the old Source deletion semantics, so
prefer keeping the reviewed server contract while reverting only the plugin.
Local Windows QGIS installation and a second physical PC are not available in
the Work deployment environment and remain separate user-machine checks.

Deploy the reviewed server contract and then publish/install the new immutable
Connector version through the existing release workflow. New client + old server
blocks Source deletion; new server + old client rejects legacy deletion. Do not
overwrite 1.4.3 objects or bypass hash checks. No DB migration is required.

Before release completion, verify new production GET metadata and L2 labels,
repeat source inventory on a separate PC/profile, and perform login/restart/Delta
checks with preserved user edits. Full real-machine restart/relogin, the new API
on production, and a second physical PC have not been exercised. Production
deletion remains untested intentionally; use the disposable regression fixture.
No exact actor/cause should be attributed to the remembered 3→2 change without
additional historical settings/backups/audit evidence.
