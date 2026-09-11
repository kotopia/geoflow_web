# GeoFlow QGIS Professional Workspace v0.8

## Goal

Provide one scalable QGIS workspace for GeoFlow-managed GIS projects without
shipping a separate tab, Python module, or `.ui` file for every physical layer.
QGIS, QField, and WebGIS continue to use the same project/profile, physical
tables, field metadata, reference catalog, Changeset, and revision Delta model.

## Source of truth

- Tables and fields: GeoFlow `gis.meta_feature_type`, `gis.meta_field_def`, and
  active profile field settings.
- Reference values: `gis.ref_code_group` and `gis.ref_code_value`, bound through
  `gis.meta_field_def.code_group_key`.
- Project scope: the server-calculated Layer Plan and QGIS manifest.
- Data: project-scoped GeoFlow `gis.*` physical tables.

Legacy workbooks and plugins are migration/reference inputs only. They never
override the GeoFlow physical schema or become runtime dependencies.

## Reference-material findings

The supplied database workbook contains 13 water-table definitions and 10
sewer-table definitions. GeoFlow already standardizes these as common survey
and road layers, nine WTL layers, and eight SWL layers; legacy error layers are
excluded and the two survey tables are unified.

The supplied IROOM and 2025 plugins use one quick-edit class and one Qt form per
layer, with option values embedded in Python. This works for a fixed small layer
set but makes every new field, code, or layer a plugin release. GeoFlow v0.8
therefore retains the useful workflows while replacing that structure.

## v0.8 baseline

### Layer workspace

The dockable layer workspace is generated from `manifest.layers` and provides:

- search by label, standard name, physical name, or domain;
- domain grouping instead of per-layer tabs;
- layer visibility, activation, extent zoom, attribute table, and add-feature
  actions;
- object count, geometry type, and automatic-sync/read-only status.

### Attribute forms

QGIS native attribute forms remain the editing surface. GeoFlow field labels
become QGIS aliases, and fields with an active reference binding become dynamic
Value Map widgets. No WTL/SWL code list is hardcoded in the plugin.

### Synchronization

- QGIS save queues a field-level Changeset and automatically sends it after the
  existing debounce interval.
- QGIS pulls authoritative Delta every 15 seconds when WebSocket hints are not
  available.
- QField continues to use the same Changeset/Delta data contract.
- An open WebGIS project polls project revision Delta every 5 seconds while
  visible (15 seconds while hidden) and reloads only changed feature IDs.
- WebSocket remains an optional hint; correctness never depends on it.

## Compatibility rules

- Import Qt APIs only through `qgis.PyQt`.
- Support QGIS 3.28+ / Qt5 and QGIS 4 / Qt6 enum forms.
- Do not expose direct PostGIS credentials.
- Do not embed tenant- or municipality-specific codes in plugin source.
- Do not overwrite or discard a Snapshot carrying pending/outbox work.

## Next increments

1. Metadata-driven required/range/conditional validation and form sections.
2. Professional geometry workflows: snapping presets, connected pipe/node
   creation, split/merge assistance, and topology/QC feedback.
3. Photo/attachment capture and survey-point linkage in the same panel.
4. QField form aliases and reference widgets generated from the same catalog,
   including offline catalog retention and refresh.
5. Favorites/recent layers, saved filters, and role/profile-specific tool
   presets for very large layer catalogs.
