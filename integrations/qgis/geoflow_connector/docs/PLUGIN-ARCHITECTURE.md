# GeoFlow Connector 1.4.3

## Object edit session

The dynamic form and its photo tab share one feature-scoped edit session.
Form values and photo changes remain in memory until the user saves. Facility
changes use the online changeset path; photo persistence requires a readable
server-side facility UUID. A failed save retains staged operations in the
current form session for retry. Photo presign/upload/finalize stages avoid
re-uploading already completed stages during that session. They are not an
offline photo queue and are not promised to survive application restart.

Photo policy is an ordered `Template → Variant → Slot` catalogue. The last valid
Template/Variant selection is kept in the current QGIS user profile per project and
layer; a stale value falls back to the first server-ordered Template/Variant. This
working preference is never written to feature `ext_data` or the central policy.

Object switches and QGIS shutdown use the same save/discard/continue guard.
Discard reloads committed feature values and removes pending in-memory photo operations. S3,
tenant photo metadata, and the QGIS feature buffer cannot form one database
transaction, so the client reports partial failures and resumes from cached
presign/upload stages rather than claiming atomicity. Legacy queued cache rows are inert: the newest
compatible dirty snapshot is selected for an explicit migration prompt without
replaying or deleting those rows during selection.

Photo Studio persists image-coordinate annotation objects in
`gis.feature_photo.edit_data` (`version=2`, `format=annotation-json`) while the
separately uploaded JPEG remains a bounded display artifact. Reopening a photo
loads its original master plus the annotation document, so line/polyline,
freehand, shape, text, and icon objects remain selectable and editable. Legacy
`raster-png` and Connector 1.3.3 `raster-jpeg` documents remain viewable and
can be replaced only through an explicit new-edit confirmation.

The 1.1.2 interaction shell is retained: one Dock, login and project pages,
Layer Workspace, Form Host and Form Header, splitter presentation, visibility
icons, retained drafts, edit-buffer protection, reusable snapshot cache and explicit save/discard/continue guards.

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

### Bundled common form layouts

`resources/forms/common_form.json` is the version-controlled default layout
resource. It preserves the eight saved WTL layouts promoted from this developer
profile on 2026-10-21, without redesign or normalization during export. The JSON
contains the existing version/layer/tabs/groups/rows/field/weight serialization,
in UTF-8 without BOM. Field labels, widget types, visibility, required/readonly
rules and style still come from the central definition and existing renderer;
they are not replaced by this presentation resource.

Resolution is per standard layer name: valid user QSettings override at
`GeoFlowConnector/formLayouts/<UPPERCASE_LAYER>` first, then that layer's bundled
layout, then the existing central-generated layout for unbundled layers or an
unreadable resource. The local profile stores these JSON strings in QGIS4.ini.
Invalid overrides remain untouched while rendering the default. There is no
project-specific local storage in this resolver; project/tenant definitions
remain server-resolved and unchanged. Existing field-ID filtering and newly
introduced field handling are preserved; the bundled layouts refer to the
current shared central field IDs, not inferred field-name replacements.

`DynamicFormHost` loads through this store and passes the result to `DynamicForm`
and `LayoutRenderer`. Save writes only the existing QSettings key. Reset previews
the bundled default and, when accepted, removes only that layer's local override.
Neither reading defaults nor installing/updating the plugin copies resources to
the profile. Runtime never writes the resource. No new UI, version bump, ZIP or
release artifact is created for this change.

Validation: `test_local_form_layout.py` covers the resource and generated fallback;
`tests/qgis_common_form_runtime.py` runs in two isolated QGIS 4.2.2 processes,
checks all eight developer overrides read-only, new-profile rendering, local
save/restart/reset, cancelled reset preview, and unchanged resource bytes.


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

### Release contract test migration

The repository contract tests now cover the current online save/session model,
photo capability/content visibility, active behavior validation fields, and
specific-before-base Qt date dispatch. They no longer require the removed
recovery JSON workflow or the old fixed photo-tab/header wiring. Cache cleanup
fixtures include photo_count; selecting legacy dirty snapshots is verified not
to mutate either file. Runtime behavior remains covered by the QGIS regression
programs recorded in release/validation-summary.json.
