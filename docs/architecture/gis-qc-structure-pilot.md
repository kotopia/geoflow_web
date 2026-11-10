# GIS QC & Structure Local Pilot

GeoFlow QC & Structure (`geoflow_qc_structure`, 0.2.0 experimental) is a
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
3. Preview displays one input object per row, output Profile fields in order,
   with a frozen FID header and horizontal scrolling. NULL, `""`, and 0 are
   distinct. Yellow cells changed; red cells have operation or Post-QC errors.
   Select a cell for old/new values, operation, QC and aggregate evidence.
   Select the object, pan or zoom from this table. The error-only switch and
   the existing field-change detail list use the same calculated result.
   Pre-QC errors stop calculation; Post-QC is also visible before execution.
4. Execute: recompute and compare preview, validate output, populate a detached
   memory layer, validate staged attributes, then add it to the map. On failure
   the detached layer is discarded. Source edits and schema are untouched.
5. Compare separate output layers. Use **결과 GeoPackage 저장** to create a new
   file, verify all values/geometries after writing, and embed Profile, code-book
   snapshots, reference fingerprints and aggregate evidence in `gpkg_metadata`.
   Existing files are rejected. Standard QGIS Export is also possible but does
   not promise to preserve the plugin's execution provenance.

`catalog.py` supplies local fields, operation contracts, QC kinds and resolved
profiles; `qc.py` and `structure.py` do not depend on QGIS. `spatial.py` supplies
geometry/CRS/reference operations; `ui.py` manages user actions and staging.
Bundled catalog is immutable. Optional local `fields.json` and numbered
`profiles/*.json` live under `QgsApplication.qgisSettingsDirPath()/geoflow_qc_structure`.
The Profile tab shows inherited mappings and overrides with per-field form
controls. COPY/KEEP lists actual input fields, CONSTANT accepts a typed value
or explicit NULL, and LENGTH/AREA select a metric calculation CRS and unit.
CODE_MAP and AGGREGATE have dedicated controls. Other advanced reference and
condition operations retain validated JSON parameter inputs. Source selection and calculation parameters are
separate from output schema. Missing output fields are created in the temporary
result. Missing explicitly selected COPY inputs remain errors. CONSTANT replaces
all output values, while COPY preserves source values, including NULL.
`field_editor.py` owns the form widgets and uses the shared operation/field
validators. New Profile revisions pin resolved rules, fields and code books,
independent of later base/catalog changes. Past revisions can be opened from
**과거 리비전 조회**; saving creates a new revision. Explicit NULL values, including
COPY, CONSTANT, code policies and empty aggregates, are never replaced by field
defaults. The output layer
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

## Reference-code management

**참조코드 관리** maintains `id`, agency, business, code kind and mapping ID.
Each entry separates a common meaning/stable ID, the agency output code/name,
and explicitly listed input aliases. There is no fuzzy matching or automatic
PE/Poly/pedc equivalence. Register every intended alias. Duplicate codes,
duplicate aliases, conflicting normalized aliases and missing required values
are rejected. Code-book scope cannot change under the same ID.

Direct table edits and Excel import both produce a reviewable draft. Choose
file, sheet and code/name/meaning/alias columns, inspect the table, validate,
then save. Excel assumes the first row contains headers. Aliases may be a
single literal or a JSON array; arrays allow explicit NULL. GDAL shipped with
QGIS reads XLSX/XLS (XLS only when that driver is present); no pip installation
or new runtime dependency. String reading preserves text code leading zeroes;
Excel numeric display formatting is not reconstructed. Review imported codes.
The header/type options follow the [GDAL XLSX driver](https://gdal.org/en/stable/drivers/vector/xlsx.html).

Code books live in local `codebooks/<id>.<revision>.json`, installed atomically
without overwriting prior revisions. Field settings select the input field,
exact output book/revision/mapping and an explicit unregistered policy: error
(default), keep source, NULL, or specified JSON value. Trim and case folding
are opt-in and collisions are checked before use. A book edit creates a new
revision; existing Profiles retain the embedded prior book until explicitly
reconfigured. They remain reproducible even if local book files are unavailable.
This is a local pilot catalog, not an alternate central `gis.definition_*` API.

## Stored-depth reference and shared aggregation

The source is **the already stored numeric depth on the user-selected water-depth
layer**. Repository evidence: `gis-initial-feature-tables-v0.1.sql` defines
`gis.wtl_pipe_ps.pip_dep numeric(10,3)`; Connector `services/depth.py` writes
`pip_dep` from the earlier Survey/H workflow. This plugin never imports that
calculator and never reads Survey raw measurements, elevations or Z to derive
depth. The existing model has no persistent Survey/asset matching relationship,
and no pipe/depth relationship was found to reuse in the inspected definitions.
Connector materialization exposes `geoflow/definition_layer_id`; retain it when
available, along with the selected QGIS layer ID, provider and hashed source
connection identity. Neither display names nor `pip_dep` are lookup conditions.
No actual customer definition UUID is invented. Missing/changed bindings or
missing/non-numeric fields fail closed without fallback.

Select the target pipe as input, then **심도 평균·최소·최대 공유 설정**. Select the
stored-depth layer, numeric field, whole layer/current selected references,
optional exact field=value filters for references and pipes, metric projected
CRS, explicit tolerance in metres, depth unit (m/cm/mm) and candidate policy.
Provider subsets are respected. Depth unit labels the stored and output values;
no implicit unit conversion occurs. The group creates three independently
named/typed output fields with identical reference settings. Edit names and
precision/scale through existing field settings. Matching settings, excluding
the statistic selector, share one indexed candidate assignment and statistics
cache during each calculation.

Every reference object is assigned to a candidate pipe within tolerance.
Default `unique` rejects multiple pipe candidates. `nearest` permits only a
unique nearest pipe; distance ties within 1e-8 m require review. Unresolved
references mark every affected pipe as an error; no first-candidate tie break.
The target filter explicitly defines the candidate pipe population; targets
outside it are reported as errors rather than silently assigned an empty mean.
Average is the arithmetic mean of valid stored values, minimum/maximum are
numeric extrema of **the same object set**. No other average definition was
found in the repository. The original full practical SQL/workbook was not
present in this checkout; equivalence to a different SQL average is unverified.

NULL is excluded and counted; 0 and negatives remain. Numeric strings and
non-finite values are rejected. Duplicate FIDs count once, distinct co-located
objects remain distinct. No valid values returns NULL plus QC warning, subject
to output nullable/required rules. Decimal calculation retains internal precision;
ROUND_HALF_UP is applied only at output scale, then precision is checked again.
The cell detail and output metadata include source layer/field, selected source
FIDs and stored values, searched/valid/excluded counts, all three statistics,
ambiguities and exact scope/CRS/radius/unit settings.

Pre-QC validates operation inputs, explicit bindings, numeric source field,
units, metric CRS, scope and candidate settings. Rules on generated output
attributes run after generation, so missing original length/constant output
columns do not block. Preview fingerprints include input values/geometries/schema,
Profile/catalog, reference values/geometries/schema/subsets/selections, and local
code-book/Profile files. Even a reference edit leaving the mean unchanged forces
a new Preview. Execution recalculates, checks the detached output and rechecks
dependencies before adding it to the project. Failure preserves source and
previously published result layers. This synchronous pilot scans reference
fingerprints for correctness; very large-layer performance has not been benchmarked.

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
0.1.1 was the previous implementation candidate. The current 0.2.0 candidate
is validated locally as described below; TEST publication is explicitly deferred
until a separate user instruction. No publisher, server deployment or migration
was invoked for this change.

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

## 0.2.0 validation record (2026-11-04)

Base: `release/stabilized-deploy` at `558c90239967bfddf84e26bc70516e86b326aa84`.
Topic: `codex/qc-preview-reference-depth`.

- 14 focused pure-Python tests passed (`scripts.qgis.test_qc_structure` and
  `scripts.qgis.test_qc_references`): generated fields, length scales, mixed
  SA200/SA203/NULL copy, constants, agency code differences, alias normalization
  conflicts, import mapping, immutable books/Profiles, null/zero/negative and
  duplicate-reference aggregation, output QC and package inventory.
- 23 additional existing package/stable-repository/publisher-contract tests
  passed. Publisher tests use mocks; their SUCCESS logs are not live publication.
- Actual installed QGIS **4.2.2**, isolated `qc_structure_test` profile, offscreen
  application: both plugins enabled, unload/reload, final initial launch PASS,
  and second launch **PASS restart** with persisted enablement. Fixtures use only
  memory layers and temporary XLSX/GeoPackage files. The user's open project and
  installed default-profile plugin were not modified.
- `qc_reference_runtime.py` covers object counts/order/values, red/yellow cells,
  NULL/empty/zero display, selection/pan/zoom, shared single-search statistics,
  missing bindings/fields, metric CRS/unit/radius rejection, unchanged-aggregate
  reference mutation invalidation, parallel/crossing/equal-nearest ambiguity,
  unique nearest, selected NULL/single-value cases, rounded precision overflow,
  source/previous-output preservation, native Excel mapping, code-editor revision
  save, GeoPackage reread/provenance and refusal to overwrite an existing file.
- Preview screenshots were captured from the application and visually inspected.
  These are programmatic native-widget checks, not a human mouse-driven acceptance
  session. Authenticated Connector login/project loading, TEST Plugin Manager
  installation, actual customer depth data and large-data performance remain
  unverified. Legacy XLS support depends on the installed GDAL driver; XLSX was tested.
- Syntax compilation and `git diff --check` passed. Existing deterministic builder
  includes all five new runtime modules: `references.py`, `reference_editor.py`,
  `operation_editor.py`, `preview_table.py`, `output.py`.

Candidate ZIP: `geoflow_qc_structure-0.2.0.zip`.
SHA256: `08a45acc3f7916c8116b18664911f68da4dbfbe2808e2946c0961e1f341bff73`.
This hash identifies the locally verified artifact; publication must verify the
actual release artifact with the existing procedure and requires separate instruction.

