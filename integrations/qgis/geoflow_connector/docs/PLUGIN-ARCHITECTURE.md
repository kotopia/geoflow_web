# GeoFlow Connector 1.4.3

## Object edit session

The dynamic form and its photo tab share one feature-scoped edit session. Form
values remain local widget drafts, while photo adds, replacements, annotation edits,
and deletes begin in a retryable in-memory queue. Only **현재 객체 저장** commits
the QGIS edit buffer. A new facility's photo add is then persisted in the local
GeoPackage `_geoflow_pending_photo` table without contacting the photo API. The
existing changeset sync hook delivers it only after the target UUID no longer has
a pending/outbox/conflict action. Normalized bytes and classification metadata
survive restart, and an uploaded-but-unfinalized identity is retried without a
second S3 PUT. The local cache is considered dirty while such rows exist.

Photo policy is an ordered `Template → Variant → Slot` catalogue. The last valid
Template/Variant selection is kept in the current QGIS user profile per project and
layer; a stale value falls back to the first server-ordered Template/Variant. This
working preference is never written to feature `ext_data` or the central policy.

Object switches and QGIS shutdown use the same save/discard/continue guard.
Discard reloads committed feature values and removes pending photo bytes. S3,
tenant photo metadata, and the QGIS feature buffer cannot form one database
transaction, so the client reports partial failures and resumes from cached
presign/upload stages rather than claiming atomicity.

Photo Studio persists image-coordinate annotation objects in
`gis.feature_photo.edit_data` (`version=2`, `format=annotation-json`) while the
separately uploaded JPEG remains a bounded display artifact. Reopening a photo
loads its original master plus the annotation document, so line/polyline,
freehand, shape, text, and icon objects remain selectable and editable. Legacy
`raster-png` and Connector 1.3.3 `raster-jpeg` documents remain viewable and
can be replaced only through an explicit new-edit confirmation.

The 1.1.2 interaction shell is retained: one Dock, login and project pages,
Layer Workspace, Form Host and Form Header, splitter presentation, visibility
icons, retained drafts, edit-buffer protection, offline cache and sync queues.

Runtime form behavior has one source:

```text
Final Layer Plan + Final Form Definition v3 + Definition Revision
    -> DefinitionService (same-origin, fail closed)
    -> DynamicForm
       -> LayoutRenderer
       -> WidgetFactory
       -> central rule evaluator
       -> DynamicFormBinding
    -> QGIS local edit buffer -> existing changeset/sync engine
```

There is no tenant legacy form fallback and no layer-specific form registry,
field map or code-group map. Reference values are loaded only from
`central.gis.definition_code` through the project reference-catalog endpoint.
When a definition is absent, invalid, cross-origin or revision-mismatched, the
form stays unavailable and existing input/edit buffers remain intact.

The Designer files under `ui/designer` and the complete 1.1.2
`resources/feather.qrc`, generated resource modules and icon set are packaged
unchanged. Layer-specific Designer forms are intentionally not runtime assets.

## Field edit tools and future override hierarchy

`ui/edit_tools.py` is a launcher over QGIS native actions. It does not replace
QGIS edit buffers, snapping, undo stacks, keyboard shortcuts, or map tools.
Business operations are separate services: project/user/layer previous-value
cache, CRS-safe `NearbyService`, and registered nearby strategies. A strategy
must receive an explicit physical-field and sign contract; ambiguous central
metadata fails closed.

There is currently no authoritative central style service in the Connector.
When one is introduced, resolution should be performed by one resolver in this
order, never by unrelated QSettings substitutes:

```text
Central Style -> Tenant override -> Project override (optional)
```

The same resolution boundary should be used for form layouts:

```text
Central default Form Layout -> Tenant override -> Project override (optional)
```

The current `LocalFormLayoutStore` remains a user-local presentation preference
and is not treated as a tenant or project-authoritative override.

### Current depth/nearby contract

`WTL_PIPE_PS.pip_dep` is the calculated pipe-depth value. `dep_dist` is not
written by this workflow. Survey import lineage supplies metre-valued `raw_z`;
the cached `SURVEY.code` is the snapshot compatibility mirror of `raw_code`.
`DepthFromNearbySurveyH` calculates `H.raw_z - source.raw_z`, rounded to three
decimal places, without ABS. Negative values require review. H uses the exact
resolved code `H`. The source is selected by management number first and otherwise
by nearest eligible Survey Point in the project's configured depth radius.
Project scope, deleted-point filtering, and source-code eligibility apply.
The radius comes from `GeoFlowSettingsService.get_depth_radius()`; batch H lookup
reuses a spatial index. No persistent Survey-to-GIS relationship is required.
Calculation only stages form/edit-buffer values; the user still saves through
the existing Dynamic Form or QGIS layer workflow.

Likewise no valve-to-manhole copy strategy is registered until a definition or
project configuration names the permitted source/target fields. `NearbyService`
only finds and orders candidates; it never decides which business attributes
to copy.

## Release packaging

The 1.4.3 release preserves the package identity and the existing QGIS 3.28?4.99 metadata range. Direct runtime verification is on QGIS 4.2.2. The repository builder excludes development tests, logs, per-user state, source-only scripts and release outputs. The cache Python package is required code and remains included. ZIP files remain untracked under the repository policy. See the release manifest and CHANGELOG for exact build and validation evidence.
