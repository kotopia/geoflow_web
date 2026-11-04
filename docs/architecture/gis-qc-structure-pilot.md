# GIS QC & Structure Local Pilot

GeoFlow QC & Structure (`geoflow_qc_structure`, 0.1.1 experimental) is a
separate QGIS plugin. It consumes explicitly selected layers in the open QGIS
project. It does not import Connector, authenticate, write to source layers,
execute user SQL/Python, or extend the server GIS catalog. Project and tenant
data remain in the providers that originally loaded them.

## Workflow and storage

1. Select a vector layer and Profile in the independent modeless window.
2. In the Profile tab, use each row's Settings button to select the output name,
   type, length/precision/scale and source-field, geometry calculation or constant
   value. Add a field for additional output attributes. Unsaved form changes apply
   to Preview immediately; save a new revision to retain them. Then run QC or recheck selected features. Inspect issue rows and zoom to geometry.
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
The Profile tab shows inherited mappings and overrides with per-field form
controls. COPY/KEEP lists actual input fields, CONSTANT accepts a typed value
or explicit NULL, and LENGTH/AREA select a metric calculation CRS and unit.
Advanced reference/code/condition operations retain validated JSON parameter
inputs in their field dialog. Source selection and calculation parameters are
separate from output schema. Missing output fields are created in the temporary
result. Missing explicitly selected COPY inputs remain errors. CONSTANT replaces
all output values, while COPY preserves source values, including NULL.
`field_editor.py` owns the form widgets and uses the shared operation/field
validators. Revisions keep resolved rules and field snapshots. The output layer
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
subset**. Version 0.1.0 copied `BYC_LEN = pip_len`; that assumption was
corrected by the user. Version 0.1.1 defaults to planar geometry LENGTH with
explicit EPSG:5186 and unit m, plus `ftr_cde = SA001`, `mng_cde = MNG002`.
The visible CRS must be reviewed for the project before execution. It
uses the Daejeon working `BYC_LEN numeric(5,2)`, not an assumed delivery
schema; the workbook lists a different delivery type. The separate base
profile outputs `pip_len`, allowing comparison from the same source. No
confirmed full Asan profile is supplied. Both fixtures with a value and NULL
were compared against the equivalent three SQL assignments in SQLite for
the original COPY mode; this remains a regression case. Geometry LENGTH now
works with no pip_len/byc_len/mng_cde input fields. Tests cover numeric(5,1)
and numeric(5,2) rounding, preserved mixed facility codes SA200/SA203/NULL,
explicit constant replacement and missing COPY inputs.
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

Status: implementation and non-QGIS tests passed. Windows CI QGIS 4.2.2
passed initial load, unload/reload, QC/preview/output and restart checks in
run 41756237602. Authenticated Connector project loading and TEST Plugin
Manager installation remain to be verified. Version 0.1.0 TEST publication
succeeded in run 41782888417 with public XML/ZIP/SHA256 checks. Version
0.1.1 is an implementation candidate pending CI runtime validation and TEST
publication.

The existing GIS deployment supports workflow_dispatch for the download
allowlist prerequisite. Register the GIS deployment and TEST publishing
workflow files on the default branch to expose their Run workflow controls,
then select release/stabilized-deploy. Both operational jobs retain the
protected production Environment. Run server deployment first, followed by
TEST publishing with package geoflow_qc_structure. Central catalog, tenant Profile DB,
server QC/executor, persistent QC findings and PostGIS delivery DDL are deferred.

The QC pilot PR runs the isolated memory fixture in the pinned OSGeo4W QGIS 4.2.2
Windows application, checking both plugins at initial launch, unload/reload,
and a second launch with enablement persisted. This does not exercise an
authenticated project or the live Plugin Manager repository.

Deployment troubleshooting: run 41780898200 stopped before code checkout or
service restart because the diff from deployed SHA 9483501 included the two
already-reviewed policy closeout documents, docs/contracts/contract-list.md
and docs/planning/GeoFlow_Product_Structure_v1.md. The GIS deploy scope permits
these exact documentation paths. Runtime files outside the GIS contract
remain rejected. Retry the current reviewed release, then publish TEST.

