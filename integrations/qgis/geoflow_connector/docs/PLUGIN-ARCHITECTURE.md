# GeoFlow Connector 1.4.0

## Object edit session

The dynamic form and its photo tab share one feature-scoped edit session. Form
values remain local widget drafts, while photo adds, replacements, annotation edits,
and deletes remain in a retryable in-memory
queue. Only **현재 객체 저장** commits the QGIS edit buffer and then executes the
existing photo presign/finalize/delete APIs. A failed remote operation remains in
the queue and is shown as unsaved so the user can retry; successful operations are
not silently replayed.

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
