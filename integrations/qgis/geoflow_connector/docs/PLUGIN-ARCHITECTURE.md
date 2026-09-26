# GeoFlow Connector 1.2.4

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
