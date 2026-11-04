# GIS QC & Structure Local Pilot

GeoFlow QC & Structure (`geoflow_qc_structure`, 0.1.0 experimental) is a
separate QGIS plugin. It consumes explicitly selected layers in the open QGIS
project. It does not import Connector, authenticate, write to source layers,
execute user SQL/Python, or extend the server GIS catalog. Project and tenant
data remain in the providers that originally loaded them.

## Workflow and storage

1. Select a vector layer and Profile in the independent modeless window.
2. Run QC or recheck selected features. Inspect issue rows and zoom to geometry.
3. Preview. An open ERROR marked blocks_structure stops calculation. Warnings
   alone do not stop it.
4. Execute: recompute and compare preview, validate output, populate a detached
   memory layer, validate staged attributes, then add it to the map. On failure
   the detached layer is discarded. Source edits and schema are untouched.
5. Compare separate output layers; use QGIS Export to keep a reviewed output.

`catalog.py` supplies local fields, operation contracts, QC kinds and resolved
profiles; `qc.py` and `structure.py` do not depend on QGIS. `spatial.py` supplies
geometry/CRS/reference operations; `ui.py` manages user actions and staging.
Bundled catalog is immutable. Optional local `fields.json` and numbered
`profiles/*.json` live under `QgsApplication.qgisSettingsDirPath()/geoflow_qc_structure`.
The Profile tab shows inherited mappings and overrides with a JSON settings
editor. Revisions keep resolved rules and field snapshots. The output layer
retains the exact resolved Profile and output field definitions. QSettings
keeps the last Profile only.

Field contracts cover scalar types, nullable/required/default, lengths,
precision/scale, reference codes and geometry metadata. Geometry is carried
separately from attributes using the source WKB and CRS. Memory-layer numeric
storage is floating point; values that cannot round-trip are rejected.
Spatial operations require a declared projected metric CRS and explicit
reference-layer IDs in the open project. Reference ambiguity is rejected unless
a unique nearest result is specified and found. ANGLE is planar, east=0°,
counterclockwise; start/end segments preserve vertex order. Multipart endpoint
ambiguity requires review. Conditions are equality with literal branches.

## Pilot evidence

Source materials: the water, sewer and QC sheets in the supplied workbook and
the accompanying SQL collection. Daejeon water pipe was selected because the
workbook and SQL both identify the working layer and provide an explicit
length alias and attribute constants. The draft Profile is **only a comparison
subset**: `BYC_LEN = pip_len`, `ftr_cde = SA001`, `mng_cde = MNG002`. It
uses the Daejeon working `BYC_LEN numeric(5,2)`, not an assumed delivery
schema; the workbook lists a different delivery type. The separate base
profile outputs `pip_len`, allowing comparison from the same source. No
confirmed full Asan profile is supplied. Both fixtures with a value and NULL
were compared against the equivalent three SQL assignments in SQLite.
This does not establish parity for the full SQL or spatial results.
Spatial join patterns and duplicate checks inform reusable rules.
Management ID assignment, largest overlap, code lists not in the evidence,
and per-vertex validation are deferred; no source workbook or SQL is packaged.

## TEST release

Build with `python scripts/qgis/build_plugin_repository.py --source
integrations/qgis/geoflow_qc_structure --output /tmp/qc-release`. Use the
existing QGIS TEST publisher and select `geoflow_qc_structure` on
`release/stabilized-deploy`. The download allowlist must first be running
on the server; previously it accepted Connector filenames only. This is a
routing change, not a GIS schema or business-rule migration. The TEST publishing
job itself does not restart services. It uploads an immutable versioned ZIP,
verifies the public download before changing the index, then updates only the
target entry with an ETag precondition. Existing entries are retained.
Before update it retains the previous XML under `qgis-plugins/test/history/`.
Rollback uses the existing publisher with `--channel test --rollback-index-key
<logged-history-key> --expected-test-index-sha256 <current-hash> --verify-http`
and the same explicit channel confirmation. An index changed since review is
not overwritten. Stable routes reject the QC package.

After HTTP checks, register https://geoflow.co.kr/gis/qgis/plugins/test/plugins.xml
in a clean QGIS 4.2.2 profile, enable experimental plugins, and verify search,
install, enable and restart. Install Connector separately in that profile.
Use a disposable profile named `qc_structure_test` and run
`scripts/qgis/qc_structure_runtime.py` from its Python console to verify
geometry operations and the two plugins' coexistence on memory fixtures.
Also verify Connector login and project load with an authorized test project,
unload/reload each plugin, and repeat after restart. The script does not
substitute for those interactive checks.

Status: implementation and non-QGIS tests prepared; real QGIS 4.2.2 and TEST
publication must be confirmed separately. Central catalog, tenant Profile DB,
server QC/executor, persistent QC findings and PostGIS delivery DDL are deferred.

The QC pilot PR runs the isolated memory fixture in the pinned OSGeo4W QGIS 4.2.2
Windows application, checking both plugins at initial launch, unload/reload,
and a second launch with enablement persisted. This does not exercise an
authenticated project or the live Plugin Manager repository.
